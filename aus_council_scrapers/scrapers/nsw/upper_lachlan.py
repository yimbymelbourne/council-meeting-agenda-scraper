import datetime
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://upperlachlan.nsw.gov.au"
_MEETINGS_URL = f"{_BASE_URL}/council/council-meetings/"
# 2017 to 2021. The meetings page holds January 2022 onwards.
_ARCHIVE_URL = f"{_BASE_URL}/council/council-meetings/archives"
_ARCHIVE_LAST_YEAR = 2021

# robots.txt sets `Crawl-delay: 10`. Only a run that wants 2021 or earlier
# makes a second request, so production (one current year) is one request.
_CRAWL_DELAY = 10

# Both pages are WordPress: an h3 per year ("2026" on the meetings page,
# "Council Meetings 2020" on the archive) over a flat run of links. Each
# meeting is an agenda, minutes and any number of item attachments, late
# reports and presentations, all labelled by hand:
#
#   "Ordinary Agenda – 15 October 2026", "Extraordinary Minutes – 8 December
#   2025", "19 October 2023 – Ordinary Minutes", "20 July 2023 – Agenda",
#   "9 May 2023 – Extraordinary Meeting – Minutes", "16 July 2020 – Agenda –
#   Part 1".
#
# Dates: the `ORD_ddmmyyyy` code in the council's own file names is the most
# reliable, then the label, then a date spelled out in the file name. Each
# rung is wrong somewhere the one above it is right:
#
#   - "Ordinary Minutes – 20 September 2026" links ORD_17092026_MIN_AT.pdf;
#     the meeting, and its agenda, are 17 September.
#   - "Ordinary Agenda – 16 July 20260" links ORD_16072026_AGN_AT.pdf.
#   - "Ordinary Agenda – 16 April 2026" links 19-April-2026-Ordinary-
#     Agenda.pdf; 19 April 2026 is a Sunday, and the minutes are ORD_16042026.
#   - "17 November 2020 – Minutes" links 19-November-2020-Minutes.pdf.
#
# Upload folders mean nothing: hundreds of papers from 2023-2026 sit in
# /2022/11/.
_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)
_ORD_CODE = re.compile(r"ORD_(\d{2})(\d{2})(\d{4})(?!\d)", re.IGNORECASE)
_LABEL_DATE = re.compile(
    r"(?<!\d)(\d{1,2})\s+(" + _MONTHS + r")\s+(\d{4})(?!\d)", re.IGNORECASE
)
_FILENAME_DATE = re.compile(
    r"(?<!\d)(\d{1,2})-(" + _MONTHS + r")-(\d{4})(?!\d)", re.IGNORECASE
)
_YEAR_HEADING = re.compile(r"^(?:Council Meetings\s+)?(\d{4})$", re.IGNORECASE)

_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
# Filed beside the agenda or minutes, never as them: "Ordinary Agenda
# Attachments – Item 11.1 …", "Ordinary Agenda – Late Agenda – Council Fuel
# Supply Update", "Late Reports Agenda", "18 May 2017 – Supplementary Item",
# "17 June 2021 – Minutes – Rail Trail Presentation". Split agendas keep
# part 1, which carries the order of business.
_NOT_THE_PAPER = re.compile(
    r"attach|\blate\b|supplementary|\bitem\b|presentation|part\s*[2-9]",
    re.IGNORECASE,
)
_EXTRAORDINARY = re.compile(r"extraordinary|_EXTRA\b", re.IGNORECASE)

# Labels from 2017 to mid-2023 say only "Agenda" or "Minutes", not which kind
# of meeting. Read on 20 Oct 2026, the minutes of every such meeting from
# 2020 on are headed "MINUTES OF THE ORDINARY MEETING OF COUNCIL" except
# these three, headed "EXTRAORDINARY MEETING OF COUNCIL". Since late 2023
# every label names its meeting type.
_UNLABELLED_EXTRAORDINARY = {
    datetime.date(2022, 6, 21),
    datetime.date(2023, 1, 23),
    datetime.date(2023, 2, 13),
}

# Labels that give the wrong date, checked against the papers. "17 November
# 2020 – Agenda" and "– Minutes" link a business paper for "Thursday 19
# November 2020" and minutes of the meeting held on 19 November 2020.
_DATE_CORRECTIONS = {datetime.date(2020, 11, 17): datetime.date(2020, 11, 19)}


@dataclass
class _Paper:
    kind: str  # "agenda" or "minutes"
    url: str
    date: datetime.date
    extraordinary: bool


def _make_date(day: str, month: str, year: str) -> Optional[datetime.date]:
    try:
        return datetime.datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date()
    except ValueError:
        return None


def _paper_date(label: str, filename: str) -> Optional[datetime.date]:
    code = _ORD_CODE.search(filename)
    if code:
        day, month, year = code.groups()
        try:
            return datetime.date(int(year), int(month), int(day))
        except ValueError:
            pass
    for pattern, text in ((_LABEL_DATE, label), (_FILENAME_DATE, filename)):
        match = pattern.search(text)
        if match:
            date = _make_date(*match.groups())
            if date:
                return date
    return None


@register_scraper
class UpperLachlanScraper(BaseScraper):
    def __init__(self):
        super().__init__("upper_lachlan", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _links(soup) -> list[tuple[int, str, str]]:
        """(heading year, href, label) for each document under a year heading.

        One label is split across two anchors to the same file ("Ordinary
        Agenda –" + "16 April 2026"), so consecutive anchors sharing an href
        are joined into one.
        """
        links: list[tuple[int, str, str]] = []
        year = None
        for element in soup.find_all(["h3", "a"]):
            if element.name == "h3":
                match = _YEAR_HEADING.match(element.get_text(" ", strip=True))
                # Any other h3 ("Archives", "Webcasts") ends the year's run.
                year = int(match.group(1)) if match else None
                continue
            href = (element.get("href") or "").strip()
            if year is None or "/wp-content/uploads/" not in href:
                continue
            label = element.get_text(" ", strip=True).replace("\xa0", " ")
            if links and links[-1][1] == href:
                links[-1] = (year, href, f"{links[-1][2]} {label}".strip())
            else:
                links.append((year, href, label))
        return links

    def _papers(self, html: str, page_url: str, wanted: set[int]) -> list[_Paper]:
        links = self._links(BeautifulSoup(html, "html.parser"))
        if not links:
            # No documents under any year heading: the page has changed
            # shape, which must not pass for a council with no meetings.
            raise ValueError(f"{self.council_name}: no year sections of papers on {page_url}")
        papers = []
        for heading_year, href, label in links:
            url = urljoin(page_url, href)
            if not url.lower().endswith(".pdf"):
                continue
            if _MINUTES.search(label):
                kind = "minutes"
            elif _AGENDA.search(label):
                kind = "agenda"
            else:
                continue
            if _NOT_THE_PAPER.search(label):
                continue
            filename = unquote(url.rsplit("/", 1)[-1])
            date = _paper_date(label, filename)
            date = _DATE_CORRECTIONS.get(date, date)
            if not date:
                if heading_year in wanted:
                    self.logger.warning(
                        f"{self.council_name}: cannot date {kind} {url}; skipped"
                    )
                continue
            if date.year not in wanted:
                continue
            text = f"{label} {filename}"
            papers.append(
                _Paper(
                    kind=kind,
                    url=url,
                    date=date,
                    extraordinary=bool(_EXTRAORDINARY.search(text))
                    or date in _UNLABELLED_EXTRAORDINARY,
                )
            )
        return papers

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Left to raise on failure: a page that cannot be read must not pass
        # for a council with no meetings.
        pages = [_MEETINGS_URL]
        if min(wanted) <= _ARCHIVE_LAST_YEAR:
            pages.append(_ARCHIVE_URL)
        papers: list[_Paper] = []
        for i, page_url in enumerate(pages):
            if i:
                self.fetcher.sleep(_CRAWL_DELAY)
            html = self.fetcher.fetch_with_requests(page_url)
            papers.extend(self._papers(html, page_url, wanted))

        meetings: dict[tuple[datetime.date, bool], dict[str, str]] = {}
        for paper in papers:
            meeting = meetings.setdefault((paper.date, paper.extraordinary), {})
            # First link wins: the same extraordinary agenda is listed twice
            # in 2024, and a later duplicate never displaces the first.
            meeting.setdefault(paper.kind, paper.url)

        results = []
        for (date, extraordinary), meeting in sorted(meetings.items()):
            name = "Extraordinary Council Meeting" if extraordinary else "Ordinary Council Meeting"
            agenda_url = meeting.get("agenda")
            minutes_url = meeting.get("minutes")
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_ARCHIVE_URL if date.year <= _ARCHIVE_LAST_YEAR else _MEETINGS_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
