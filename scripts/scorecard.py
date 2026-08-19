#!/usr/bin/env python3
"""Report how close each council scraper is to the target.

Everything here is *derived* from the recorded fixtures — nothing is stored.
A committed scorecard would be a second, staler copy of what the cassettes
already say, and a single file that every scraper PR would need to rewrite.

Two kinds of finding, deliberately kept apart:

  invariants  things that are wrong *now* — duplicate meetings, dates that
              do not parse, relative URLs, no meetings at all. These are
              defects regardless of how finished a scraper is.

  coverage    how much of the target a scraper reaches — how many meetings,
              how many years, whether minutes are found. Being short here
              means unfinished, not broken, and it is what progress is
              measured against.

Usage:
    python scripts/scorecard.py            # table + rollup
    python scripts/scorecard.py --json     # machine-readable
    python scripts/scorecard.py --gaps     # only what is not yet complete
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dateutil.parser import parse as parse_date  # noqa: E402

from aus_council_scrapers import clock  # noqa: E402
from aus_council_scrapers.constants import EARLIEST_YEAR  # noqa: E402

CASSETTE_GLOB = "tests/test-cases/*-result.json"
COUNCILS_DOC = "docs/councils.md"

# A scraper is "complete" when it reaches all of these.
TARGET_MIN_MEETINGS = 2
TARGET_MIN_YEARS = 2


def _year_of(date_str: str) -> int | None:
    try:
        return parse_date(str(date_str), fuzzy=True).year
    except Exception:
        return None


def assess(slug: str, meetings: list[dict]) -> dict:
    invariants: list[str] = []
    coverage: list[str] = []

    if not meetings:
        return {
            "slug": slug,
            "meetings": 0,
            "years": [],
            "agenda": 0,
            "minutes": 0,
            "invariants": ["returns no meetings"],
            "coverage": [],
            "status": "broken",
        }

    # --- invariants -------------------------------------------------------
    unparseable = [m for m in meetings if _year_of(m.get("date")) is None]
    if unparseable:
        invariants.append(f"{len(unparseable)} unparseable date(s)")

    # Two meetings sharing a name and date are not automatically a bug: a
    # council can hold two special meetings on one night, and a supplementary
    # agenda is a real second document. Only rows that are identical in every
    # field are the scraper emitting the same meeting twice.
    by_identity: dict[tuple, list[dict]] = {}
    for m in meetings:
        by_identity.setdefault((m.get("name"), m.get("date")), []).append(m)

    same_slot = {k: v for k, v in by_identity.items() if len(v) > 1}
    exact_duplicates = [
        k for k, v in same_slot.items() if all(row == v[0] for row in v)
    ]
    if exact_duplicates:
        invariants.append(f"{len(exact_duplicates)} meeting(s) emitted twice")

    # One meeting arriving as an agenda-only row plus a minutes-only row is a
    # modelling failure rather than a duplicate: it defeats the point of
    # carrying agenda and minutes on the same record.
    split_documents = [
        k
        for k, v in same_slot.items()
        if k not in exact_duplicates
        and any(r.get("agenda_url") and not r.get("minutes_url") for r in v)
        and any(r.get("minutes_url") and not r.get("agenda_url") for r in v)
    ]

    url_fields = ("agenda_url", "minutes_url", "agenda_html_url", "minutes_html_url")
    relative = [
        url
        for m in meetings
        for url in (m.get(f) for f in url_fields)
        if url and not re.match(r"^https?://", url)
    ]
    if relative:
        invariants.append(f"{len(relative)} relative URL(s)")

    undated = [m for m in meetings if not m.get("date")]
    if undated:
        invariants.append(f"{len(undated)} meeting(s) with no date")

    # --- coverage ---------------------------------------------------------
    years = sorted({y for m in meetings if (y := _year_of(m.get("date")))})
    agenda = sum(1 for m in meetings if m.get("agenda_url") or m.get("download_url"))
    minutes = sum(1 for m in meetings if m.get("minutes_url"))

    this_year = clock.current_year()
    past = [m for m in meetings if (y := _year_of(m.get("date"))) and y < this_year]
    past_with_minutes = sum(1 for m in past if m.get("minutes_url"))

    if split_documents:
        coverage.append(
            f"{len(split_documents)} meeting(s) split across agenda/minutes rows"
        )
    if len(meetings) < TARGET_MIN_MEETINGS:
        coverage.append(f"only {len(meetings)} meeting(s)")
    if len(years) < TARGET_MIN_YEARS:
        coverage.append(f"only {len(years)} year(s)")
    if past and not past_with_minutes:
        coverage.append("no minutes on any past meeting")
    if agenda == 0:
        coverage.append("no agendas")
    if years and years[0] > EARLIEST_YEAR:
        coverage.append(f"history starts {years[0]}, target {EARLIEST_YEAR}")
    if years and years[-1] < this_year:
        coverage.append(f"nothing newer than {years[-1]}")

    status = "broken" if invariants else ("complete" if not coverage else "partial")
    return {
        "slug": slug,
        "meetings": len(meetings),
        "years": years,
        "agenda": agenda,
        "minutes": minutes,
        "invariants": invariants,
        "coverage": coverage,
        "status": status,
    }


def load_recorded() -> list[dict]:
    rows = []
    for path in sorted(glob.glob(CASSETTE_GLOB)):
        slug = os.path.basename(path).replace("-result.json", "")
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = [data]
        rows.append(assess(slug, data))
    return rows


def tracked_slugs() -> set[str]:
    """Slugs from the councils doc — the honest denominator.

    Counting only councils that already have a scraper would hide every
    council nobody has started.
    """
    if not os.path.exists(COUNCILS_DOC):
        return set()
    slugs = set()
    with open(COUNCILS_DOC) as f:
        for line in f:
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and re.fullmatch(r"[a-z0-9_]+", cells[-1]):
                slugs.add(cells[-1])
    return slugs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--gaps", action="store_true", help="only incomplete scrapers")
    args = parser.parse_args()

    rows = load_recorded()
    tracked = tracked_slugs()
    recorded = {r["slug"] for r in rows}
    unstarted = sorted(tracked - recorded)

    if args.json:
        print(json.dumps({"scrapers": rows, "unstarted": unstarted}, indent=2))
        return 0

    shown = [r for r in rows if not args.gaps or r["status"] != "complete"]
    print(f"{'council':22}{'status':10}{'mtgs':>6}{'yrs':>5}{'agenda':>8}{'minutes':>9}  notes")
    print("-" * 100)
    for r in sorted(shown, key=lambda r: (r["status"] != "broken", r["slug"])):
        span = f"{r['years'][0]}-{r['years'][-1]}" if r["years"] else "-"
        notes = "; ".join(r["invariants"] + r["coverage"])
        print(
            f"{r['slug']:22}{r['status']:10}{r['meetings']:>6}{len(r['years']):>5}"
            f"{r['agenda']:>8}{r['minutes']:>9}  {span}"
            + (f"  {notes}" if notes else "")
        )

    counts = Counter(r["status"] for r in rows)
    total = len(tracked | recorded)
    complete = counts["complete"]
    print()
    print(
        f"{complete} complete, {counts['partial']} partial, {counts['broken']} broken, "
        f"{len(unstarted)} not started — {complete}/{total} councils "
        f"({100 * complete // total if total else 0}%)"
    )
    if unstarted:
        print(f"\nnot started: {', '.join(unstarted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
