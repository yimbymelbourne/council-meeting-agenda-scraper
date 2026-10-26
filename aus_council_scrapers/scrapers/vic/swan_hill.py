"""Swan Hill Rural City Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting: Ordinary
("Scheduled") Meetings, Unscheduled Meetings and, in 2020, Special Meetings,
all of the council, so nothing is filtered out. The listing includes the next
meeting with its agenda (20 October 2026).

Papers are one flat "Related information" list beside the livestream links,
labelled "Agenda - Scheduled Meeting - 15 September 2026", "Unconfirmed
Minutes - …", "Minutes - …". The labels are copied by hand and sometimes
wrong, while the filenames follow one pattern throughout ("agenda19052020.pdf",
"minutes_08_april_2025.pdf"). So `papers` classifies a file by its filename
when the filename names one paper, and by its label otherwise:

* 19 May 2020 labels both files "Minutes - Ordinary Meeting - 23 June 2020";
  they are agenda19052020.pdf and minutes19052020.pdf.
* 15 April 2025 offers agenda_15_april_2025.pdf twice, once labelled
  "Minutes"; the meeting is reported with its agenda and no minutes.
* 21 November 2023's minutes are "cminutes211123.pdf", which names nothing
  cleanly, and are read by their label.

Some days hold two meetings, told apart by a time in the label and page
address: "Unscheduled Meeting - 26 October 2021 (12pm)" and "(5pm)". The
payload gives both the same time, so `build_return` takes the time from the
label when one is there.

The listing dates the 4 November 2021 Unscheduled Meeting as 16 November;
its page and papers say 4 November, and `meeting_date` uses that. Its
payload's time, 2:00 PM, is wrong too: the agenda and minutes both say it
commenced at 9am, and `_TIME_FIXES` gives that.

One production year is the listing page and a payload per meeting: 12
requests for 2026.
"""

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import (
    _AGENDA,
    _MINUTES,
    _NOT_THE_PAPER,
    ListingRow,
    _is_pdf,
    _label,
    _papers,
    _pick,
)
from aus_council_scrapers.scrapers.vic._regional_opencities import (
    RegionalOpenCitiesScraper,
)

# In a filename the word runs into the date ("agenda19052020"), so only a
# letter on either side disqualifies it.
_FILE_AGENDA = re.compile(r"(?<![a-z])agendas?(?![a-z])")
_FILE_MINUTES = re.compile(r"(?<![a-z])minutes(?![a-z])")

# Times the site gets wrong, by the meeting's date, checked against page 1 of
# its papers. Applied only to a row `meeting_date` has redated, so another
# meeting on the same date keeps the time the site gives.
_TIME_FIXES = {
    # agenda04112021.pdf: "Commencing at 9am"; minutes04112021.pdf:
    # "Commenced at 9am". The payload says 02:00 PM.
    "04 November 2021": "09:00 AM",
}

_LABEL_TIME = re.compile(r"\((\d{1,2}(?::\d{2})?\s*[ap]m)\)", re.IGNORECASE)


def _file_kind(url: str) -> str | None:
    name = urlparse(url).path.rsplit("/", 1)[-1].lower()
    agenda, minutes = _FILE_AGENDA.search(name), _FILE_MINUTES.search(name)
    if agenda and not minutes:
        return "agenda"
    if minutes and not agenda:
        return "minutes"
    return None


def _label_kind(label: str) -> str | None:
    if _AGENDA.search(label):
        return "agenda"
    if _MINUTES.search(label):
        return "minutes"
    return None


@register_scraper
class SwanHillScraper(RegionalOpenCitiesScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 23 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 23

    papers_by = "link_text"

    def __init__(self):
        super().__init__(
            "swan_hill",
            "VIC",
            "https://www.swanhill.vic.gov.au/Our-Council/Councillors-and-meetings/Agendas-and-Minutes",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        found: dict[str, list[tuple[str, str, int]]] = {"agenda": [], "minutes": []}
        for anchor in content.find_all("a", href=True):
            href = anchor["href"].strip()
            if not _is_pdf(href):
                continue
            label = _label(anchor.get_text(" ", strip=True))
            name = _label(urlparse(href).path.rsplit("/", 1)[-1].replace("-", " "))
            if _NOT_THE_PAPER.search(label) or _NOT_THE_PAPER.search(name):
                continue
            kind = _file_kind(href) or _label_kind(label)
            if kind:
                found[kind].append((label, urljoin(self.base_url, href), 0))
        return _papers(_pick(found["agenda"]), _pick(found["minutes"]))

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        record = super().build_return(content, row)
        if record is None:
            return None
        times = {
            match.group(1).replace(" ", "").lower()
            for anchor in content.find_all("a", href=True)
            if _is_pdf(anchor["href"].strip())
            for match in _LABEL_TIME.finditer(anchor.get_text(" ", strip=True))
        }
        if len(times) == 1:
            record.time = parse_date(times.pop()).strftime("%I:%M %p")
        if record.date != row.date and record.date in _TIME_FIXES:
            record.time = _TIME_FIXES[record.date]
        return record
