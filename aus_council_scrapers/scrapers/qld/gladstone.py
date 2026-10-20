"""Gladstone Regional Council—OpenCities, on `OpenCitiesMeetingsScraper`, plus
a static archive page.

Two sources, which overlap by a month:

* **The meetings list** (``OC CL Public Meetings``) holds General, Special,
  Special Budget and Post Election meetings from August 2025, upcoming ones
  included, with a year filter offering 2025, 2026 and an empty 2018. Every
  row is a meeting of Council, so nothing is filtered out. Headings name the
  meeting first—"General Meeting Agenda 15 September 2026", "Special Meeting
  Notice and Agenda 1 October 2026"—so ``papers_by = "search"``. A heading
  that is only a notice ("Special Budget Meeting Notice 21 July 2026")
  names neither paper and is passed over.
* **The archive page** (``/Council/Meetings/Agendas-and-Minutes-Archive``)
  is one static page holding 16 January 2024 to 16 September 2025, a panel
  per meeting headed "General Meeting 2 September 2025" with the agenda,
  the minutes and every item's attachments as links (`_archive`). A meeting
  the list also holds (19 August to 16 September 2025) is taken from the
  list, which has both papers where the archive's 19 August panel has only
  the agenda. The page is fetched only when a wanted year is one it holds,
  so a production run for 2026 never requests it.

Nothing earlier is online: the archive page says the minutes from 15 March
2008 to 23 January 2024 are available only as scans at the Gladstone
Regional Libraries.

In both sources the agenda's own links are followed by every item's
attachments, some of which are other meetings' minutes ("Item 2.1 - Attach
01 - Minutes of the General Meeting held 2 September 2025"). A labelled
attachment is never the paper, here or in the base class.

robots.txt disallows nothing on the meeting paths. The site is behind
Akamai; the project fetcher gets 200.

One production year is 20 requests: the list filtered to that year at
``page_size`` 50 (19 rows in 2026), then a payload per meeting.
"""

import datetime
import re

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import (
    OpenCitiesMeetingsScraper,
    papers_by_link_text,
)

_ARCHIVE_URL = (
    "https://www.gladstone.qld.gov.au/Council/Meetings/Agendas-and-Minutes-Archive"
)
# The years the archive page holds (16 January 2024 to 16 September 2025).
_ARCHIVE_YEARS = frozenset({2024, 2025})
# "General Meeting - 16 September 2025", "Special Budget Meeting 3 July 2025".
_PANEL_HEADING = re.compile(
    r"^(?P<name>.*?\bmeeting)\s*[-–—:]?\s*(?P<date>\d{1,2}\s+[a-z]+\s+\d{4})$",
    re.IGNORECASE,
)
# One item's attachment: "Item 4.1 - Attach 01 - ...", "Item 4.10 - Existing
# P-2015-37 ... Policy".
_ITEM = re.compile(r"^item\b|\battach\b", re.IGNORECASE)


@register_scraper
class GladstoneScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 38 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 38

    list_name = "OC CL Public Meetings"
    papers_by = "search"
    # The busiest year is 19 rows (2026): one listing page a year.
    page_size = 50
    # The year-filtered page offers every year in its dropdown (checked
    # 20 October 2026), so production skips the bare first page.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "gladstone",
            "QLD",
            "https://www.gladstone.qld.gov.au/Council/Meetings/Agendas-and-Minutes",
        )

    def scraper(self) -> list[ScraperReturn]:
        results = super().scraper()
        wanted = self._wanted_years() & _ARCHIVE_YEARS
        if not wanted:
            return results
        listed = set()
        for record in results:
            listed.add((record.name, parse_date(record.date, dayfirst=True).date()))
        for record in self._archive(wanted):
            if (record.name, parse_date(record.date).date()) not in listed:
                results.append(record)
        return results

    def _archive(self, years: set[int]) -> list[ScraperReturn]:
        """The archive page's meetings in `years`. A failed fetch raises:
        nothing else holds them."""
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_ARCHIVE_URL), "html.parser"
        )
        records = []
        for panel in soup.find_all("div", class_="oc-wysiwyg-container-panel"):
            heading = panel.find("h2")
            match = _PANEL_HEADING.match(
                re.sub(r"\s+", " ", heading.get_text(" ", strip=True))
                if heading
                else ""
            )
            if not match:
                continue
            try:
                date = parse_date(match.group("date")).date()
            except (ValueError, OverflowError):
                continue
            if date.year not in years:
                continue
            body = BeautifulSoup("", "html.parser")
            for anchor in panel.find_all("a", href=True):
                if not _ITEM.search(anchor.get_text(" ", strip=True)):
                    body.append(anchor.__copy__())
            papers = papers_by_link_text(body, self.base_url)
            if not papers:
                continue
            records.append(self._archive_record(match.group("name"), date, papers))
        if not records:
            raise RuntimeError(f"{_ARCHIVE_URL}: no meetings read for {sorted(years)}")
        return records

    def _archive_record(
        self, name: str, date: datetime.date, papers: dict[str, str]
    ) -> ScraperReturn:
        agenda = papers.get("agenda")
        minutes = papers.get("minutes")
        return ScraperReturn(
            name=re.sub(r"\s+", " ", name).strip(),
            date=f"{date:%d %B %Y}",
            time=None,
            webpage_url=_ARCHIVE_URL,
            agenda_url=agenda,
            minutes_url=minutes,
            download_url=agenda or minutes,
        )
