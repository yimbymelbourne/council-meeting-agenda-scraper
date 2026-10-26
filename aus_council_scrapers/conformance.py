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

# Gaps the counts above cannot see: a body or a stretch of years the council
# publishes but the scraper does not read. Each keeps its council `partial`,
# with the reason in the notes, so the scorecard does not call it complete.
# Remove an entry in the change that closes the gap.
KNOWN_GAPS: dict[str, str] = {
    "benalla": (
        "papers before Feb 2025 not read (site document archive, an admin-ajax "
        "search; 2023 Council minutes are there)"
    ),
    "brisbane": (
        "papers before mid-2025 are Word files, which are not emitted: 6 "
        "meetings in 2020-2023, none in 2024"
    ),
    "mount_barker": (
        "assessment panel before Sep 2026 not read (council-domain list "
        "behind Cloudflare)"
    ),
    # Labelled by month only and dated from their PDFs (`pdf_dates`) or a
    # `misfiled` entry read off the cover: a meeting whose papers give no
    # day that can be trusted is left out rather than given one.
    "northern_peninsula_area": (
        "Sep 2026 Trustee meeting left out: its agenda is a scan with no text"
    ),
    "mckinlay": (
        "Feb 2020 special meeting left out: its agenda says Tuesday 7th "
        "February 2020, which was a Friday, and its minutes are a scan"
    ),
    "temora": (
        "only the latest agenda is online, so past meetings have minutes "
        "only; a month-only minutes published after 26 Oct 2026 is left out "
        "until its day is added to `misfiled` (each file is 5-210 MB, too "
        "large to read nightly)"
    ),
    "winton": (
        "5 meetings left out, their papers scans with no text: Jul 2023 "
        "ordinary, and the Apr 2020 statutory, Jul 2021 and Jul 2023 budget "
        "and Nov 2021 special meetings"
    ),
    "yalgoo": (
        "Apr 2022 special meeting left out: its papers say both 13 April "
        "and Tuesday, and 13 April 2022 was a Wednesday"
    ),
    # Queensland Resolve tenants whose record starts when the council moved
    # to Resolve; the earlier papers are on the council's own site.
    "bundaberg": "2020 to Jul 2022 not read (per-year accordions on the council site)",
    "charters_towers": "2020 to Oct 2022 not read (council-site archive page)",
    "gympie": "2020 to Apr 2024 not read (council-site Meetings-Archive)",
    "hinchinbrook": "2020-2023 minutes not read (council-site Archived-Minutes; no agendas)",
    "noosa": "2020 to Mar 2023 not read (council-site OpenCities archive)",
    "toowoomba": (
        "20 of 22 Ordinary meetings Jun 2020-Mar 2022 and nine 2020-21 specials "
        "are unpublished in the Resolve API; the tenant host is robots-disallowed"
    ),
    "torres_strait_island": (
        "Jul 2025 ordinary and Apr 2020 statutory meetings left out: titled "
        "by month only, and their PDFs' first page gives no day"
    ),
    "gingin": (
        "minutes before mid-2023 not emitted: their only address is the "
        "robots-disallowed file store"
    ),
    "mount_marshall": (
        "ordinary meetings are labelled by month only and dated from the "
        "meeting-dates page, which lists the current year alone, so 2021-2025 "
        "ordinary meetings are left out (about 55; 15 and 22 April 2025 are "
        "dated in their labels), as are a few month-only special and "
        "electors' meetings"
    ),
    "woodanilling": (
        "Oct 2020 special meeting left out: labelled by month only, and its "
        "papers' first page gives only the date the CEO signed them"
    ),
    # SharePoint councils, under the documented robots.txt exception.
    "fraser_coast": (
        "current year only: earlier years are a SharePoint folder archive, "
        "which has no plain-download form, and are not read"
    ),
    "mount_magnet": (
        "no 2026 papers published anywhere on the site (checked 26 Oct 2026), "
        "so a production run fails; agendas linked only for 2023-2024"
    ),
    "huon_valley": (
        "most agendas are SharePoint folder shares and are left out (16 of 89 "
        "meetings carry one), so upcoming meetings are mostly not emitted until "
        "their minutes are up; Jan-Aug 2020 and Mar-Apr 2021 papers are on "
        "Google Drive and not read"
    ),
    "carrathool": (
        "only the current year is read: the meetings page holds one year, "
        "and the Feb 2023-Dec 2025 archive page labels papers by month only"
    ),
    # Dated from their PDFs (`pdf_dates`): a meeting whose first page cannot
    # be read cheaply, or gives no day in the label's month, is left out.
    "coolamon": (
        "agendas are taken down after each meeting, so past meetings have "
        "minutes only (one left behind, Oct 2024); Mar 2022 and Aug 2023 "
        "left out (minutes past 8 MB)"
    ),
    "carpentaria": (
        "18 meetings 2020-2024 left out: neither paper's cover is in its "
        "first 256 KB, and both files are past 2 MB (minutes are text-less scans)"
    ),
    "kowanyama": (
        "Sep 2023 and Jun 2026 ordinary meetings left out: the minutes give "
        "no day in the month (Jun 2026's say 30 May) and the pack is past 8 MB"
    ),
    "mapoon": (
        "most 2020 meetings (9) and the Jul 2024 budget meeting left out: "
        "no day readable on the papers' first page"
    ),
    "wollongong": (
        "Local Planning Panel not read: its agendas (about 95 since 2020) are "
        "on its own allowed page, with per-application decisions and no minutes"
    ),
}


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
    if slug in KNOWN_GAPS:
        result.coverage.append(KNOWN_GAPS[slug])

    return result
