import datetime
import json
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote_plus

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://coomalie.nt.gov.au"
# A Duda site, served pre-rendered: one page with an h3 per year, an h5 per
# meeting ("17 October 2026", "6 October 2026 - Special Meeting", "20 July
# 2026 - Finance Committee Meeting"), and under each a run of hand-typed
# links to PDFs on Duda's CDN (irp.cdn-website.com). Labels carry typos
# ("Piubic Agenda", "Miniutes", "Minuets", "Sepcial") and sometimes the
# wrong day, so the heading dates a meeting wherever it can.
_LISTING_URL = f"{_BASE_URL}/council-meetings"

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
# "17 October 2026", "21st October", "05 December".
_DAY_FIRST = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s*" + _MONTH + r"\b", re.IGNORECASE)
# "April 15th 2025", "December 16th 2025"; a bare "February 25" is a year
# ("Confirmed Public Minutes February 25"), so a day here needs an ordinal
# or a year after it.
_MONTH_FIRST = re.compile(
    r"\b" + _MONTH + r"\s+(\d{1,2})(?:(?:st|nd|rd|th)\b|(?=\s+\d{4}))", re.IGNORECASE
)
_FILE_ISO = re.compile(r"(?<!\d)(20\d\d)-(\d\d)-(\d\d)(?!\d)")
_FILE_DAY_MONTH_YEAR = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s_\-]+" + _MONTH + r"[\s_\-]+(20\d\d)", re.IGNORECASE
)
# A label's day and the file's can differ by a day or two for one meeting.
_FILE_DATE_TOLERANCE_DAYS = 3

_MINUTES = re.compile(r"\bmin(?:ut|iut|ue|tu)[a-z]*", re.IGNORECASE)
_AGENDA = re.compile(r"\bagend", re.IGNORECASE)
# Agenda-item attachments ("Agenda Item 14.1 Attachment: ...") are not the
# agenda.
_NOT_A_PAPER = re.compile(r"attachment|agenda\s+item", re.IGNORECASE)
_CONFIRMED = re.compile(r"confirmed|\bconf\b|final", re.IGNORECASE)

_BODIES = (
    (re.compile(r"cemetery", re.IGNORECASE), "Cemetery Board Meeting"),
    (re.compile(r"finance", re.IGNORECASE), "Finance Committee Meeting"),
    (re.compile(r"audit", re.IGNORECASE), "Audit Committee Meeting"),
    # "Special", "SPecial", "Sepcial", "Secial", "Spewcial", and run into
    # the word before it ("Public AgendaSpecial Meeting").
    (re.compile(r"s(?:pe|ep|e|pew)c?ial\b", re.IGNORECASE), "Special Meeting"),
)
_ORDINARY = "Ordinary General Meeting"


def _body(text: str) -> Optional[str]:
    for pattern, name in _BODIES:
        if pattern.search(text):
            return name
    return None


def _day_month(text: str) -> Optional[tuple[int, int]]:
    match = _DAY_FIRST.search(text)
    if match:
        return int(match.group(1)), _MONTHS[match.group(2)[:3].lower()]
    match = _MONTH_FIRST.search(text)
    if match:
        return int(match.group(2)), _MONTHS[match.group(1)[:3].lower()]
    return None


def _file_date(filename: str) -> Optional[datetime.date]:
    match = _FILE_ISO.search(filename)
    try:
        if match:
            return datetime.date(*(int(g) for g in match.groups()))
        match = _FILE_DAY_MONTH_YEAR.search(filename)
        if match:
            day, month, year = match.groups()
            return datetime.date(int(year), _MONTHS[month[:3].lower()], int(day))
    except ValueError:
        pass
    return None


def _date(year: int, day_month: tuple[int, int]) -> Optional[datetime.date]:
    try:
        return datetime.date(year, day_month[1], day_month[0])
    except ValueError:
        return None


@dataclass
class _Paper:
    kind: str  # "agenda" or "minutes"
    url: str
    filename: str
    label: str
    body: str
    date: datetime.date


@register_scraper
class CoomalieScraper(BaseScraper):
    def __init__(self):
        super().__init__("coomalie", "NT", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _papers(self, html: str) -> list[_Paper]:
        soup = BeautifulSoup(html, "html.parser")
        papers = []
        year: Optional[int] = None
        heading_text = ""
        for element in soup.find_all(["h3", "h5", "a"]):
            if element.name == "h3":
                # The 2025 heading carries a stray byte-order mark.
                text = element.get_text(" ", strip=True).replace("\ufeff", "").strip()
                if re.fullmatch(r"\d{4}", text):
                    year, heading_text = int(text), ""
                continue
            if element.name == "h5":
                heading_text = element.get_text(" ", strip=True)
                continue
            href = element.get("href", "").strip()
            if year is None or not href.lower().endswith(".pdf"):
                continue
            label = element.get_text(" ", strip=True)
            filename = unquote_plus(href.rsplit("/", 1)[-1])
            if _NOT_A_PAPER.search(label):
                continue

            # The label names the paper; a label with neither word ("Public
            # Meeting 17th May 2022", "Special Meeting 27 April 2023") or
            # both ("Special Agenda Mintues") is settled by the file name.
            in_label = {k for k, p in (("agenda", _AGENDA), ("minutes", _MINUTES)) if p.search(label)}
            if len(in_label) != 1:
                in_label = {k for k, p in (("agenda", _AGENDA), ("minutes", _MINUTES)) if p.search(filename)}
            if len(in_label) != 1:
                continue
            kind = in_label.pop()

            heading_body = _body(heading_text) or _ORDINARY
            body = _body(label) or heading_body
            heading_day = _day_month(heading_text)
            label_day = _day_month(label)
            # Section year, not the label's: "Confirmed Cemetery Board
            # Minutes 15 October 2025" sits in 2024 and is the 2024 paper.
            #
            # The heading dates its own meeting. "Public OGM Agenda 20
            # November 2025" under "27 November 2025" is the agenda for the
            # meeting its minutes say sat on the 27th. Only a paper for
            # another body ("Special Meeting Agenda 8 July 2024" under "16
            # July 2024"), or one under a month-only heading ("October
            # 2024"), takes its label's day.
            if heading_day and body == heading_body:
                date = _date(year, heading_day)
            else:
                date = _date(year, label_day or heading_day) if (label_day or heading_day) else None
            if not date:
                self.logger.warning(f"{self.council_name}: cannot date {label!r} ({href}); skipped")
                continue

            # Papers dated only by a heading are checked against a dated file
            # name: "Cemetery Board Agenda April 2024" under 16 April 2024 is
            # `2024-04-23 RMAC Agenda.pdf`, another meeting's.
            file_date = _file_date(filename)
            if (
                not label_day
                and file_date
                and abs((file_date - date).days) > _FILE_DATE_TOLERANCE_DAYS
            ):
                self.logger.warning(
                    f"{self.council_name}: {filename} is dated {file_date}, not {date}; skipped"
                )
                continue
            # An ordinary-meeting link to a Cemetery Board or Finance file
            # ("Minutes 15 December 2020") is that body's paper.
            if body == _ORDINARY and _body(filename) not in (None, "Special Meeting"):
                continue
            papers.append(_Paper(kind, href, filename, label, body, date))
        return self._drop_reused(papers)

    @staticmethod
    def _drop_reused(papers: list[_Paper]) -> list[_Paper]:
        """Keep a file linked twice only where its file name dates it.

        "Cemetery Board Minutes 15 June 2021" links
        `Cemetery_Board_Minutes_16_June_2020.pdf`, which is also the 16 June
        2020 meeting's.
        """
        by_url: dict[str, list[_Paper]] = {}
        for paper in papers:
            by_url.setdefault(paper.url, []).append(paper)
        kept = []
        for paper in papers:
            uses = by_url[paper.url]
            if len(uses) > 1:
                file_date = _file_date(paper.filename)
                matching = [p for p in uses if file_date and p.date == file_date]
                if matching and paper not in matching:
                    continue
            kept.append(paper)
        return kept

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Left to raise: this page is the only request, and failing quietly
        # would report the council as having no meetings.
        body = self.fetcher.fetch_with_requests(_LISTING_URL)
        # Duda answers our fetcher's Accept header with its page payload, a
        # JSON object whose "content" is the page body, rather than the
        # rendered HTML a browser gets. Either is read.
        html = body
        if body.lstrip().startswith("{"):
            html = json.loads(body).get("content") or ""

        meetings: dict[tuple[datetime.date, str], dict[str, _Paper]] = {}
        for paper in self._papers(html):
            if paper.date.year not in wanted:
                continue
            docs = meetings.setdefault((paper.date, paper.body), {})
            current = docs.get(paper.kind)
            # First listed wins, except that confirmed or final minutes
            # replace a draft listed before them.
            if current is None or (
                paper.kind == "minutes"
                and _CONFIRMED.search(paper.label)
                and not _CONFIRMED.search(current.label)
            ):
                docs[paper.kind] = paper

        results = []
        for (date, body), docs in sorted(meetings.items()):
            agenda_url = docs["agenda"].url if "agenda" in docs else None
            minutes_url = docs["minutes"].url if "minutes" in docs else None
            results.append(
                ScraperReturn(
                    name=body,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
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
