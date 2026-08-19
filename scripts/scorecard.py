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

from aus_council_scrapers.conformance import assess  # noqa: E402

CASSETTE_GLOB = "tests/test-cases/*-result.json"
COUNCILS_DOC = "docs/councils.md"


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
    recorded = {r.slug for r in rows}
    unstarted = sorted(tracked - recorded)

    if args.json:
        payload = [
            {
                **{k: v for k, v in vars(r).items()},
                "status": r.status,
            }
            for r in rows
        ]
        print(json.dumps({"scrapers": payload, "unstarted": unstarted}, indent=2))
        return 0

    shown = [r for r in rows if not args.gaps or r.status != "complete"]
    print(f"{'council':22}{'status':10}{'mtgs':>6}{'yrs':>5}{'agenda':>8}{'minutes':>9}  notes")
    print("-" * 100)
    for r in sorted(shown, key=lambda r: (r.status != "broken", r.slug)):
        notes = "; ".join(r.invariants + r.coverage)
        print(
            f"{r.slug:22}{r.status:10}{r.meetings:>6}{len(r.years):>5}"
            f"{r.agenda:>8}{r.minutes:>9}  {r.span}"
            + (f"  {notes}" if notes else "")
        )

    counts = Counter(r.status for r in rows)
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
