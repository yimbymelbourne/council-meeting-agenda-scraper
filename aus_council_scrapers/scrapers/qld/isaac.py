"""Isaac Regional Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting from 2020, and its
year filter is exact: the per-year counts add up to the unfiltered listing's
359 results (checked 20 October 2026). With ``(pagesize=N)`` a year is one
listing request; 2022, the busiest, has 58 rows.

The renderer payload is one flat "Related Information" list labelled by
filename, so ``papers_by = "link_text"``:
"PUBLIC_Agenda___Ordinary_Meeting___Wednesday_14_December_2022.pdf",
"Confirmed_Minutes___Ordinary_Meeting___…", and from 2023 both
"Unconfirmed-Minutes-…" and "Confirmed-Minutes-…" on one meeting, where the
confirmed ones win. Item attachments ride in the same list and are passed
over.

Most rows are standing committees—about 40 of a year's 50. Fetched
(`meeting_types`): Ordinary and Special Meetings, the post-election
Statutory Meeting, and the Planning, Environment and Community Services
standing committee (PECS) for as long as it existed, since it was the
planning body. In late 2025 the committees were reorganised, and PECS's
successor is "Community Services" (its 2026 papers sit in the same ``pecs``
folder). Its 8 September 2026 agenda holds community grants and programs,
not development matters, so it is left out with the other committees.
Each kept row is a payload request, so one production year is about 10
requests for 2026 and about 22 for a year with PECS in it.

Two rows carry papers that are not theirs, both caught by the full date
every filename here spells out:

* The 13 May 2025 PECS row lists its own agenda beside the unconfirmed
  minutes of the 8 April 2025 meeting ("…-Tuesday-8-April-2025.pdf"). A
  paper whose label names a different full date from its row is passed over
  (`row_papers`), so that meeting reports its agenda and no minutes rather
  than another meeting's minutes. Every other paper's label carries its
  row's date or none (checked across the 2020–2026 recording).
* The row dated 27 April 2022 (Special Meeting, cvid ``3d83c53a-…``) holds
  "Agenda - Special Meeting - Tuesday 27 April 2021" and its confirmed
  minutes, which open "held on Tuesday, 27 April 2021". No 2021 row exists
  for that meeting, so the row's date is corrected (`_DATE_FIXES`). It sits
  in the 2022 listing, so a one-year run for 2021 will not find it; the
  ordinary meeting of 27 April 2022 is a separate row and is unaffected.

The site is behind Akamai (``Server-Timing: ak_p``), which served the
identifying User-Agent without a challenge from a home IP; it has not been
measured from a GitHub runner. robots.txt disallows nothing under
``/Your-Council/Council-Meetings`` or ``OCServiceHandler.axd``.
"""

import re

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import (
    ListingRow,
    OpenCitiesMeetingsScraper,
    _label,
)

_COUNCIL_AND_PLANNING = re.compile(
    r"^(?:Ordinary Meeting|Special Meeting|Statutory\b"
    r"|Standing Committee - Planning, Environment and Community Services)"
)

# A full date in a filename-style label: "Tuesday_14_December_2022",
# "Tuesday-8-April-2025".
_FULL_DATE = re.compile(
    r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august"
    r"|september|october|november|december)\s+(20\d\d)\b",
    re.IGNORECASE,
)

# Listing rows whose date is wrong, by cvid; see the module docstring.
_DATE_FIXES = {
    "3d83c53a-845a-4092-819b-7f7f4619919a": "27 April 2021",
}


def _row_date(row: ListingRow):
    return parse_date(_DATE_FIXES.get(row.cvid, row.date), dayfirst=True).date()


@register_scraper
class IsaacScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 18 s
    # (10 requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 18

    list_name = "OC CL Public Meetings"
    papers_by = "link_text"
    page_size = 100
    year_filtered_first_page = True
    meeting_types = _COUNCIL_AND_PLANNING

    def __init__(self):
        super().__init__(
            "isaac",
            "QLD",
            "https://www.isaac.qld.gov.au/Your-Council/Council-Meetings",
        )

    def row_papers(self, content: BeautifulSoup, row: ListingRow) -> dict[str, str]:
        # A copy, so the links removed here are still counted when the base
        # class warns about a meeting whose every paper was rejected—a typo
        # in a year would otherwise drop the meeting without a word.
        content = BeautifulSoup(str(content), "html.parser")
        meeting_date = _row_date(row)
        for anchor in content.find_all("a", href=True):
            label = _label(anchor.get_text(" ", strip=True).replace("-", " "))
            match = _FULL_DATE.search(label)
            if not match:
                continue
            named = parse_date(" ".join(match.groups())).date()
            if named != meeting_date:
                anchor.decompose()
        return super().row_papers(content, row)

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        record = super().build_return(content, row)
        if record is not None and row.cvid in _DATE_FIXES:
            record.date = _DATE_FIXES[row.cvid]
        return record
