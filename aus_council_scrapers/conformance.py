"""What a council scraper is required to produce, and how close it is.

Two kinds of finding, kept deliberately apart because they mean different
things and are treated differently by CI:

`invariants`
    Things that are wrong *now*, regardless of how finished a scraper is: a
    meeting emitted twice, a date that will not parse, a relative URL, no
    meetings at all. These fail the build. They are never baselined or
    excused — a wrong date does not become acceptable because the scraper is
    young.

`coverage`
    How much of the target a scraper reaches: how many years of history, how
    many meetings, whether minutes are found. Falling short here means
    unfinished rather than broken, so it is reported and tracked but does not
    fail the build.

Both are computed from the recorded fixture. Nothing is stored: a committed
scorecard would be a staler copy of what the fixtures already say, and a
single file that every scraper PR would have to rewrite and conflict over.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock

# A scraper is "complete" when it reaches all of these.
#
# Note what is deliberately absent: how far back the history goes. That was
# measured against EARLIEST_YEAR, which is a *fetch bound* — don't bother
# requesting pages older than this — and reusing it as a coverage target
# judged scrapers on something they do not control. Banyule offers 2017-2026
# in its own filter but publishes nothing before 2022, so it could never pass,
# however well written it was.
#
# The span each scraper reaches is still reported in the table, so a start
# date that looks too recent stays visible for a human to investigate.
TARGET_MIN_MEETINGS = 2
TARGET_MIN_YEARS = 3

_URL_FIELDS = ("agenda_url", "minutes_url", "agenda_html_url", "minutes_html_url")


@dataclass
class Assessment:
    slug: str
    meetings: int = 0
    years: list[int] = field(default_factory=list)
    agenda: int = 0
    minutes: int = 0
    invariants: list[str] = field(default_factory=list)
    coverage: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.invariants:
            return "broken"
        return "complete" if not self.coverage else "partial"

    @property
    def span(self) -> str:
        return f"{self.years[0]}-{self.years[-1]}" if self.years else "-"


def year_of(date_str) -> int | None:
    try:
        return parse_date(str(date_str), fuzzy=True).year
    except Exception:
        return None


def assess(slug: str, meetings: list[dict]) -> Assessment:
    result = Assessment(slug=slug, meetings=len(meetings))

    if not meetings:
        result.invariants.append("returns no meetings")
        return result

    # --- invariants -------------------------------------------------------
    unparseable = [m for m in meetings if year_of(m.get("date")) is None]
    if unparseable:
        result.invariants.append(f"{len(unparseable)} unparseable date(s)")

    undated = [m for m in meetings if not m.get("date")]
    if undated:
        result.invariants.append(f"{len(undated)} meeting(s) with no date")

    # Two meetings sharing a name and date are not automatically a bug: a
    # council can hold two special meetings on one night, and a supplementary
    # agenda is a real second document. Only rows identical in every field
    # are the scraper emitting the same meeting twice.
    by_identity: dict[tuple, list[dict]] = {}
    for m in meetings:
        by_identity.setdefault((m.get("name"), m.get("date")), []).append(m)

    same_slot = {k: v for k, v in by_identity.items() if len(v) > 1}
    exact_duplicates = [k for k, v in same_slot.items() if all(r == v[0] for r in v)]
    if exact_duplicates:
        result.invariants.append(f"{len(exact_duplicates)} meeting(s) emitted twice")

    relative = [
        url
        for m in meetings
        for url in (m.get(f) for f in _URL_FIELDS)
        if url and not re.match(r"^https?://", url)
    ]
    if relative:
        result.invariants.append(f"{len(relative)} relative URL(s)")

    # --- coverage ---------------------------------------------------------
    result.years = sorted({y for m in meetings if (y := year_of(m.get("date")))})
    result.agenda = sum(
        1 for m in meetings if m.get("agenda_url") or m.get("download_url")
    )
    result.minutes = sum(1 for m in meetings if m.get("minutes_url"))

    this_year = clock.current_year()
    past = [m for m in meetings if (y := year_of(m.get("date"))) and y < this_year]

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
    if split_documents:
        result.coverage.append(
            f"{len(split_documents)} meeting(s) split across agenda/minutes rows"
        )
    if len(meetings) < TARGET_MIN_MEETINGS:
        result.coverage.append(f"only {len(meetings)} meeting(s)")
    if len(result.years) < TARGET_MIN_YEARS:
        result.coverage.append(f"only {len(result.years)} year(s)")
    if past and not any(m.get("minutes_url") for m in past):
        result.coverage.append("no minutes on any past meeting")
    if result.agenda == 0:
        result.coverage.append("no agendas")
    if result.years and result.years[-1] < this_year:
        result.coverage.append(f"nothing newer than {result.years[-1]}")

    return result
