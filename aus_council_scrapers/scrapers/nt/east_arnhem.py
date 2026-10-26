import datetime
import json
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup
from requests.utils import requote_uri

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://eastarnhem.nt.gov.au"

# A Duda site. Ordinary and special meetings each have one page listing every
# paper since 2021 under year headings, as links whose labels lead with an
# ISO date: "2026-02-26 Meeting of Council Ordinary Agenda", "2024-04-24
# Ordinary Council Minutes", "2023-06-29 Ordinary Council Meeting Agenda part
# 1". Files are on Duda's CDN (irp.cdn-website.com).
#
# Both pages are always read: they are the scraper's only two requests, and
# each holds every year.
_PAGES = {
    f"{_BASE_URL}/our-council/council-meetings/ordinary-meetings": "Ordinary Council Meeting",
    f"{_BASE_URL}/our-council/council-meetings/special-meetings": "Special Council Meeting",
}

# The label's date is the meeting's; file names drift from it
# ("2024-12-12 … Minutes" is Meeting_of_Council_20241202_Minutes.pdf, the
# "2024-01-10" special agenda is "… Open - 2023-01-10.pdf"). Both were
# checked against the minutes, which record 12 December 2024 and 10 January
# 2024.
_ISO_DATE = re.compile(r"^\s*(20\d\d)-(\d\d)-(\d\d)(?!\d)")
# Letter boundaries rather than \b, which treats "_" as part of a word and so
# misses "…_27092024_Agenda.pdf".
_MINUTES = re.compile(r"(?<![a-z])minutes(?![a-z])", re.IGNORECASE)
_AGENDA = re.compile(r"(?<![a-z])agenda(?![a-z])", re.IGNORECASE)
# Filed beside the papers, never as them: notices of meeting and of
# postponement, supplementary and late items (and their minutes), and the
# later parts of an agenda split into several files—part 1 carries the
# order of business.
_NOT_THE_PAPER = re.compile(
    r"notice|postpone|supplementar|\blate\b|part\s*[2-9]", re.IGNORECASE
)

# How far apart an agenda and minutes can be dated and still be one meeting.
# Meetings can run over two days: the April 2023 agenda is dated the 27th
# and its minutes, labelled the 28th, record a meeting opened on Thursday
# 27 April 2023.
_TWO_DAY_MEETING = 2

# A meeting postponed after its agenda was published: the agenda keeps the
# original date and the minutes the day it sat. The minutes are headed "5
# September 2024 (Originally Scheduled on 21 August 2024)".
_POSTPONED = {datetime.date(2024, 8, 21): datetime.date(2024, 9, 5)}


@dataclass
class _Paper:
    kind: Optional[str]  # "agenda", "minutes", or None when unlabelled
    url: str
    date: datetime.date


def _content_html(body: str) -> str:
    """The page's HTML, whether Duda served the page or its JSON payload.

    Duda answers a client whose Accept header prefers JSON—ours does—with
    the page as a JSON object whose `content` field is the rendered HTML. A
    browser gets the HTML page itself. Either is handled.
    """
    stripped = body.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except ValueError:
            return body
        if isinstance(payload, dict) and isinstance(payload.get("content"), str):
            return payload["content"]
    return body


@register_scraper
class EastArnhemScraper(BaseScraper):
    def __init__(self):
        super().__init__("east_arnhem", "NT", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _papers(self, html: str, page_url: str) -> list[_Paper]:
        soup = BeautifulSoup(_content_html(html), "html.parser")
        papers = []
        for anchor in soup.find_all("a", href=True):
            label = anchor.get_text(" ", strip=True).replace("\xa0", " ")
            match = _ISO_DATE.match(label)
            if not match:
                continue  # Navigation, and "Postponement Notice" links.
            url = requote_uri(urljoin(page_url, anchor["href"].strip()))
            # Two papers are Word files (a 2024 special agenda and a set of
            # supplementary minutes); only PDFs are recorded.
            if not url.lower().endswith(".pdf"):
                continue
            if _NOT_THE_PAPER.search(label):
                continue
            filename = unquote(url.rsplit("/", 1)[-1])
            # Classified by label, then by file name ("2024-09-27 Special
            # Council Meeting 27092024" is …_27092024_Agenda.pdf), else left
            # open for _assign_unlabelled.
            kind = None
            for text in (label, filename):
                if _MINUTES.search(text):
                    kind = "minutes"
                elif _AGENDA.search(text):
                    kind = "agenda"
                if kind:
                    break
            try:
                date = datetime.date(*(int(g) for g in match.groups()))
            except ValueError:
                self.logger.warning(f"{self.council_name}: bad date in {label!r}; skipped")
                continue
            papers.append(_Paper(kind=kind, url=url, date=_POSTPONED.get(date, date)))
        return papers

    @staticmethod
    def _group(papers: list[_Paper]) -> dict[datetime.date, dict[str, str]]:
        meetings: dict[datetime.date, dict[str, str]] = {}
        for paper in papers:
            if paper.kind:
                # First link wins; the page lists each meeting's current
                # upload first.
                meetings.setdefault(paper.date, {}).setdefault(paper.kind, paper.url)
        # "2025-05-21 Special Council Meeting" names neither agenda nor
        # minutes in its label or its file name; the PDF is the open
        # minutes. An unlabelled paper is taken as the minutes only when its
        # meeting already has an agenda and no minutes.
        for paper in papers:
            if paper.kind:
                continue
            meeting = meetings.get(paper.date)
            if meeting and "agenda" in meeting and "minutes" not in meeting:
                meeting["minutes"] = paper.url
        return meetings

    @staticmethod
    def _join_two_day_meetings(meetings: dict[datetime.date, dict[str, str]]) -> None:
        """Join an agenda and minutes dated a day or two apart.

        Only when each is the other's sole candidate, and under the agenda's
        date, the day the meeting opened.
        """
        def lone(kind: str) -> list[datetime.date]:
            return [d for d, papers in meetings.items() if set(papers) == {kind}]

        for agenda_date in lone("agenda"):
            near = [
                d for d in lone("minutes") if 0 < (d - agenda_date).days <= _TWO_DAY_MEETING
            ]
            if len(near) != 1:
                continue
            rivals = [
                d for d in lone("agenda") if 0 <= (near[0] - d).days <= _TWO_DAY_MEETING
            ]
            if rivals != [agenda_date]:
                continue
            meetings[agenda_date]["minutes"] = meetings.pop(near[0])["minutes"]

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        results = []
        for page_url, name in _PAGES.items():
            # Left to raise on failure: each page is the only listing of its
            # meeting type.
            html = self.fetcher.fetch_with_requests(page_url)
            papers = self._papers(html, page_url)
            if not papers:
                raise ValueError(f"{self.council_name}: no dated papers on {page_url}")
            meetings = self._group(papers)
            self._join_two_day_meetings(meetings)
            for date, docs in sorted(meetings.items()):
                if date.year not in wanted:
                    continue
                results.append(
                    ScraperReturn(
                        name=name,
                        date=date.isoformat(),
                        time=None,
                        webpage_url=page_url,
                        agenda_url=docs.get("agenda"),
                        minutes_url=docs.get("minutes"),
                        download_url=docs.get("agenda") or docs.get("minutes"),
                    )
                )

        if not results:
            self.logger.warning(f"{self.council_name} found no meetings for {sorted(wanted)}")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
