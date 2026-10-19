import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.portstephens.nsw.gov.au"
_INDEX_URL = f"{_BASE_URL}/council/council-meetings/council-agendas-and-minutes"

# One Squiz page per year. The index links the recent years ("2026 Council
# agendas and minutes"); everything from 2006 to 2024 sits under an archive
# page ("Council agendas and minutes 2023"). 2024 is on both, and the
# top-level copy is the cleaner of the two (the archive copy calls one set of
# minutes "Attachment 2 - 22 October 2024 - Ordinary Council Minutes"), so a
# year found on the index is never read from the archive.
#
# Documents are links to the council's TRIM records
# (`/trim/other?RecordNumber=26%2F30911`), which serve the PDF itself. A few
# point at Squiz assets (`/__data/assets/pdf_file/...`) instead.
#
# TRIM cuts every document off at 15,360,000 bytes. The 8 June 2021 agenda
# and minutes (listed at 18.4 MB and 23.2 MB) both arrive at exactly that
# length, with no %%EOF, and no PDF reader opens them (checked 20 Oct 2026).
# The URLs are still the right records and the page offers no other copy,
# so they are emitted as they are; papers under that size arrive whole.
_RECENT_YEAR_LINK = re.compile(r"^(20\d\d)\s+council agendas and minutes$", re.I)
_ARCHIVE_LINK = re.compile(r"^20\d\d\s+to\s+20\d\d\s+council agendas and minutes$", re.I)
_ARCHIVE_YEAR_LINK = re.compile(r"^council agendas and minutes\s+(20\d\d)$", re.I)
_DOCUMENT_HREF = re.compile(r"/trim/|/__data/assets/", re.I)

# Each label is "<date> - <body> Agenda|Minutes[ - <what>]": "24 March 2026 -
# Ordinary Council Agenda", "... Agenda - Mayoral Minutes", "... Agenda -
# Supplementary Information", "... Agenda - Attachments under separate cover
# - Part 1". Only the bare agenda and the minutes are the meeting's papers.
# The archive tiles also print "Published dd/mm/yyyy", the upload date,
# which is never the meeting's.
_DATE = re.compile(
    r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{4})\b",
    re.I,
)
_NOT_A_PAPER = re.compile(
    r"mayoral|supplementary|attachment|tabled|notices?\s+of\s+motion|late\s+item",
    re.I,
)
_MINUTES = re.compile(r"\bminutes\b|\bcouncil\s+record\b", re.I)  # "8 March 2022 - Ordinary Council record"
_AGENDA = re.compile(r"\bagenda\b", re.I)
_KIND_WORD = re.compile(r"\b(agenda|minutes|record)\b", re.I)

# Big papers are split: "Agenda - Items 1 to 6 - pages 1 to 193" and "Items 7
# to 9 ...", or "Minutes - Website - Pages 308 -548" listed before "Pages
# 1-307". The part that starts the document is the one kept.
_PART = re.compile(r"\b(?:pages?|items?|part)\s*(\d+)", re.I)


def _clean(text: str) -> str:
    text = text.replace("\xa0", " ").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


@register_scraper
class PortStephensScraper(BaseScraper):
    def __init__(self):
        super().__init__("port_stephens", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

    @staticmethod
    def _links(soup: BeautifulSoup, pattern: re.Pattern, page_url: str) -> dict:
        found = {}
        for link in soup.find_all("a", href=True):
            match = pattern.match(_clean(link.get_text(" ", strip=True)))
            if match:
                key = int(match.group(1)) if match.groups() else 0
                found.setdefault(key, urljoin(page_url, link["href"]))
        return found

    def _year_pages(self, wanted: set[int]) -> dict[int, str]:
        index = self._soup(_INDEX_URL)
        pages = self._links(index, _RECENT_YEAR_LINK, _INDEX_URL)
        if clock.current_year() in wanted and clock.current_year() not in pages:
            raise ValueError(f"No {clock.current_year()} page linked from {_INDEX_URL}")

        if any(y < min(pages, default=9999) for y in wanted):
            archive = self._links(index, _ARCHIVE_LINK, _INDEX_URL)
            if not archive:
                raise ValueError(f"No archive link on {_INDEX_URL}")
            archive_url = archive[0]
            for year, url in self._links(
                self._soup(archive_url), _ARCHIVE_YEAR_LINK, archive_url
            ).items():
                pages.setdefault(year, url)
        return {y: u for y, u in pages.items() if y in wanted}

    @staticmethod
    def _label(link) -> str:
        # Archive pages are tiles: the label is the tile title, and the rest
        # of the link is the upload date and the file size.
        title = link.select_one(".smp-tiles-article__title")
        return _clean((title or link).get_text(" ", strip=True))

    @staticmethod
    def _date(label: str) -> Optional[tuple]:
        match = _DATE.search(label)
        if not match:
            return None
        try:
            return match, parse_date(match.group(), dayfirst=True).date()
        except ValueError:
            # "0 June 2025 - Attachments under separate cover": a typo, on a
            # document that is not a paper anyway.
            return None

    def _meetings(self, page_url: str) -> list[ScraperReturn]:
        soup = self._soup(page_url)
        content = soup.select_one(".page-content") or soup
        meetings: dict[tuple, dict] = {}
        seen_hrefs = set()
        for link in content.find_all("a", href=True):
            href = urljoin(page_url, link["href"])
            if not _DOCUMENT_HREF.search(href) or href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            label = self._label(link)
            if _NOT_A_PAPER.search(label):
                continue
            if _MINUTES.search(label):
                field = "minutes_url"
            elif _AGENDA.search(label):
                field = "agenda_url"
            else:
                continue
            dated = self._date(label)
            if dated is None:
                continue
            match, date = dated

            after_date = label[match.end():]
            kind_word = _KIND_WORD.search(after_date)
            body = after_date[: kind_word.start()] if kind_word else ""
            body = re.sub(r"\bmeeting\b", "", body, flags=re.I).strip(" -")
            body = body or "Council"

            meeting = meetings.setdefault((date, body.lower()), {"body": body})
            part_match = _PART.search(label[match.end():])
            part = int(part_match.group(1)) if part_match else 0
            if field not in meeting or part < meeting[field][0]:
                meeting[field] = (part, href)

        results = []
        for (date, _), meeting in meetings.items():
            agenda_url = meeting.get("agenda_url", (0, None))[1]
            minutes_url = meeting.get("minutes_url", (0, None))[1]
            results.append(
                ScraperReturn(
                    name=f"{meeting['body']} Meeting",
                    date=date.isoformat(),
                    time=None,
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

        results: list[ScraperReturn] = []
        for year, url in sorted(self._year_pages(wanted).items()):
            for meeting in self._meetings(url):
                if int(meeting.date[:4]) in wanted:
                    results.append(meeting)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
