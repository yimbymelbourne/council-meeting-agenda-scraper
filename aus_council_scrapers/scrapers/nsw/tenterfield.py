import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from requests.utils import requote_uri

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.tenterfield.nsw.gov.au"
_MEETINGS_URL = f"{_BASE_URL}/your-council/council-committee-meetings"
_CURRENT_URL = f"{_MEETINGS_URL}/council-business-papers"
# Despite the path, this index links every earlier year, 2025 included
# (whose page sits outside the 2016-2024 folder), so year pages are read from
# it rather than built.
_INDEX_URL = f"{_MEETINGS_URL}/council-business-papers-2016-2024"

# Tenterfield's WordPress theme lists meetings as "downloads" blocks: a
# heading naming the meeting and its date ("AGENDA, ATTACHMENTS - Ordinary
# Council Meeting - 23 SEPTEMBER 2026") over a list of files. Usually one
# block per meeting, but late 2022 splits a meeting over several ("AGENDA,
# ATTACHMENTS - WEDNESDAY 23 NOVEMBER 2022", "ATTACHMENTS - ...", "OTHER -
# ...", the last holding the adopted minutes), so blocks are grouped by the
# date in their heading.
#
# A block holds far more than the agenda and minutes: addendum agendas,
# budget reviews, the minutes of other bodies tabled as reports ("BROC
# Minutes 19 May 2023", "LTC Meeting Minutes 7.12.23"), and the previous
# meeting's unadopted minutes. So a document is taken as a meeting's minutes
# only when its own label carries that meeting's date, which also lets the
# previous meeting's minutes, filed a month late under the next heading,
# reach the right meeting.
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ]
    )
}
_DATE = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s,]+"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s,]+(\d{4})",
    re.IGNORECASE,
)
# Two extraordinary meetings sat on 29 January 2021, at 9.30 and 10.30 am,
# under one heading; the papers' labels carry the time.
_TIME = re.compile(r"(?<!\d)(\d{1,2})[.:](\d{2})\s*([ap])\.?m\b", re.IGNORECASE)
_YEAR_LINK = re.compile(r"council business papers\W*(\d{4})$", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b|business paper", re.IGNORECASE)
_NOT_AGENDA = re.compile(r"addendum|supplementary", re.IGNORECASE)
# Reports tabled with the agenda: "QBR December 2024 Business Paper
# Attachment V3", "01. QBR March 2024 ...", "Updated Page 337 Agenda ...
# Attachment 1". The agenda itself is published "+ Attachments", "Plus
# Attachments", "With Attachments" or "No Attachments", so the word alone
# does not rule a label out.
_ATTACHMENT = re.compile(
    r"business paper attachment|attachment\s*\d|^\d+\.\s", re.IGNORECASE
)
_NO_ATTACHMENTS = re.compile(r"\b(?:no|without) attachments?\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_OTHER_BODY = re.compile(
    r"committee|\bARIC\b|\bLTC\b|\bBROC\b|\bCMA\b|\bMDA\b|association|advisory|finance",
    re.IGNORECASE,
)
_ADOPTED = re.compile(r"(?<!un)adopted|signed|confirmed", re.IGNORECASE)
_UNADOPTED = re.compile(r"unadopted|draft", re.IGNORECASE)
_EXTRAORDINARY = re.compile(r"extra\s*-?\s*ordinary", re.IGNORECASE)
_ORDINARY = re.compile(r"(?<!extra)(?<!extra )(?<!extra-)\bordinary\b", re.IGNORECASE)


def _date(text: str) -> Optional[datetime.date]:
    match = _DATE.search(text)
    if not match:
        return None
    day, month, year = match.groups()
    try:
        return datetime.date(int(year), _MONTHS[month[:3].lower()], int(day))
    except ValueError:
        return None


def _time(text: str) -> Optional[str]:
    match = _TIME.search(text)
    if not match:
        return None
    hour, minute, half = match.groups()
    return f"{int(hour)}:{minute} {half.lower()}m"


def _minutes_rank(label: str) -> int:
    # Unadopted minutes go up straight after the meeting; the adopted or
    # signed version is added beside them a month or more later.
    if _ADOPTED.search(label):
        return 0
    if _UNADOPTED.search(label):
        return 2
    return 1


@register_scraper
class TenterfieldScraper(BaseScraper):
    def __init__(self):
        super().__init__("tenterfield", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _year_pages(self, years: set[int]) -> dict[int, str]:
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_INDEX_URL), "html.parser"
        )
        pages = {}
        for anchor in soup.find_all("a", href=True):
            match = _YEAR_LINK.search(anchor.get_text(" ", strip=True))
            if match and int(match.group(1)) in years:
                pages.setdefault(
                    int(match.group(1)), urljoin(_INDEX_URL, anchor["href"])
                )
        return pages

    @staticmethod
    def _agendas(
        links: list[tuple[str, str]], date: datetime.date
    ) -> list[tuple[str, str]]:
        candidates = [
            (label, url)
            for label, url in links
            if _AGENDA.search(label)
            and not _NOT_AGENDA.search(label)
            and not _ATTACHMENT.search(label)
            # A dated label for another day is a paper filed under the
            # wrong heading, not this meeting's agenda.
            and _date(label) in (None, date)
        ]
        # Where an agenda is published both with and without its
        # attachments, the complete one is the business paper. Where it is
        # split into parts, the first part is listed first.
        complete = [c for c in candidates if not _NO_ATTACHMENTS.search(c[0])]
        return complete or candidates

    @staticmethod
    def _minutes(
        links: list[tuple[str, str]], date: datetime.date
    ) -> list[tuple[str, str]]:
        candidates = [
            (label, url)
            for label, url in links
            if _MINUTES.search(label)
            and not _OTHER_BODY.search(label)
            and _date(label) == date
        ]
        # sorted() is stable, so the page's own order breaks ties.
        return sorted(candidates, key=lambda c: _minutes_rank(c[0]))

    def _page_meetings(
        self, html: str, page_url: str, wanted: set[int]
    ) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        headings: dict[datetime.date, list[str]] = {}
        block_links: dict[datetime.date, list[tuple[str, str]]] = {}
        page_links: list[tuple[str, str]] = []
        for block in soup.select("div.downloads-list"):
            heading = block.find("h3")
            heading_text = (
                re.sub(r"\s+", " ", heading.get_text(" ", strip=True))
                if heading
                else ""
            )
            links = []
            for anchor in block.select(".downloads-list__item__name a[href]"):
                label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
                href = anchor["href"].strip()
                if label and href:
                    links.append((label, requote_uri(urljoin(page_url, href))))
            page_links.extend(links)
            date = _date(heading_text)
            if date is None:
                if links:
                    self.logger.warning(
                        f"{self.council_name}: cannot date heading {heading_text!r} on {page_url}; skipped"
                    )
                continue
            headings.setdefault(date, []).append(heading_text)
            block_links.setdefault(date, []).extend(links)

        results = []
        for date in sorted(headings):
            if date.year not in wanted:
                continue
            agendas = self._agendas(block_links[date], date)
            minutes = self._minutes(page_links, date)
            if not agendas and not minutes:
                continue

            # Split only where the papers name distinct sittings.
            times = sorted({t for label, _ in agendas if (t := _time(label))})
            sittings = times if len(times) > 1 else [None]
            for sitting in sittings:
                agenda = next(
                    (c for c in agendas if sitting is None or _time(c[0]) == sitting),
                    None,
                )
                minute = next(
                    (c for c in minutes if sitting is None or _time(c[0]) == sitting),
                    None,
                )
                papers = [c for c in (agenda, minute) if c]
                if not papers:
                    continue

                # The 2020 and 2021 headings carry only the date ("AGENDA,
                # ATTACHMENTS & MINUTES - 14 OCTOBER 2020"); the papers say
                # which kind of meeting it was.
                heading_text = " ".join(headings[date])
                if _EXTRAORDINARY.search(heading_text):
                    extraordinary = True
                elif _ORDINARY.search(heading_text):
                    extraordinary = False
                else:
                    extraordinary = any(
                        _EXTRAORDINARY.search(label) for label, _ in papers
                    )
                agenda_url = agenda[1] if agenda else None
                minutes_url = minute[1] if minute else None
                results.append(
                    ScraperReturn(
                        name=(
                            "Extraordinary Council Meeting"
                            if extraordinary
                            else "Ordinary Council Meeting"
                        ),
                        date=date.isoformat(),
                        time=sitting,
                        webpage_url=page_url,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        this_year = clock.current_year()

        # The current page holds this year's meetings, and last year's until
        # they move to their own page, so a production run for this year
        # reads it alone.
        pages = []
        if any(year >= this_year - 1 for year in wanted):
            pages.append(_CURRENT_URL)
        earlier = {year for year in wanted if year < this_year}
        if earlier:
            year_pages = self._year_pages(earlier)
            missing = sorted(earlier - set(year_pages) - {this_year - 1})
            if missing:
                self.logger.warning(f"{self.council_name}: no year page for {missing}")
            pages.extend(year_pages[year] for year in sorted(year_pages))

        results = []
        seen = set()
        for page_url in pages:
            # Left to raise: an unreadable page is a year of meetings
            # missing, which must fail the council rather than pass as a
            # short list.
            html = self.fetcher.fetch_with_requests(page_url)
            for meeting in self._page_meetings(html, page_url, wanted):
                key = (meeting.date, meeting.time)
                if key in seen:
                    continue
                seen.add(key)
                results.append(meeting)

        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return sorted(results, key=lambda m: (m.date, m.time or ""))
