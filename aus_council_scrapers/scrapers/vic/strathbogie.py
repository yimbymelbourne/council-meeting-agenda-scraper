import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.strathbogie.vic.gov.au"
_MEETINGS_URL = f"{_BASE_URL}/meetings/"
_ARCHIVE_URL = f"{_BASE_URL}/meetings/archive/"

# Strathbogie (WordPress behind Sucuri) links every agenda and minutes PDF
# straight off two pages:
#
# * /meetings/ holds 2021 to now: one `h3` per year, then a FAQ-style block
#   per meeting whose question is the meeting ("Ordinary Council Meeting
#   20/10/2026") and whose answer links its papers. The next meeting's agenda
#   appears here before the meeting.
# * /meetings/archive/ holds 2020 and earlier, as an `h4` per meeting
#   ("Council Meeting 15/12/20") followed by its links. It is read only when
#   a wanted year is older than anything on the main page, so production,
#   which asks for the current year, costs one request.
#
# Meeting blocks also carry item attachments ("20240820_Item 11.1.1_
# Attachment 1_..."), urgent-business papers, confidential-business
# certificates and budget appendices. Those are filtered out by their labels,
# and only links that name an agenda or minutes are kept.
#
# robots.txt (checked 20 Oct 2026) disallows nothing, but opens with
# `Crawl-delay: 10`. It sits above the `User-agent: *` line, so strictly it
# belongs to no group; it is honoured anyway, between the two pages.
_CRAWL_DELAY_SECONDS = 10

_NOT_A_PAPER = re.compile(
    r"\bitems?\b|attachment|appendix|urgent\s+business|certificate|confidential",
    re.IGNORECASE,
)
_MINUTES = re.compile(r"\bminutes?\b|\bmintues\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
# The meeting heading's date: dd/mm/yyyy on the main page, dd/mm/yy in the
# archive.
_HEADING_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b")


def _heading_date(text: str) -> Optional[datetime.date]:
    match = _HEADING_DATE.search(text)
    if not match:
        return None
    year = int(match[3])
    try:
        return datetime.date(
            year + 2000 if year < 100 else year, int(match[2]), int(match[1])
        )
    except ValueError:
        return None


def _meeting_type(heading: str) -> str:
    """The kind of meeting a heading names, in the council's own words.

    Strathbogie called them special meetings until 2020 and extraordinary
    meetings from 2021, and its ordinary meetings plain "Council Meeting"
    until 2025. "Extraordinary Council Meeting, including Annual Statutory
    Meeting" is the extraordinary meeting that took in the statutory
    business, so extraordinary is checked first.
    """
    lowered = heading.lower()
    if "extraordinary" in lowered:
        return "Extraordinary Council Meeting"
    if "statutory" in lowered:
        return "Statutory Council Meeting"
    if "special" in lowered:
        return "Special Council Meeting"
    return "Ordinary Council Meeting"


def _kind(label: str, href: str) -> Optional[str]:
    """ "agenda", "minutes" or None for one link in a meeting's block.

    The label decides, and the file name is the fallback: the 6 October 2026
    agenda is labelled only "20261006 Extraordinary Council Meeting 6
    October 2026".
    """
    if not label or _NOT_A_PAPER.search(label):
        return None
    filename = re.sub(r"[_-]", " ", unquote(href.rsplit("/", 1)[-1]))
    for text in (label, filename):
        if _MINUTES.search(text):
            return "minutes"
        if _AGENDA.search(text):
            return "agenda"
    return None


def _blocks(soup: BeautifulSoup) -> list[tuple[str, list]]:
    """(heading, links) for each meeting on either page."""
    blocks = []
    for item in soup.select("div.faqBlock__item"):
        question = item.select_one(".question")
        answer = item.select_one(".answer")
        if question and answer:
            blocks.append(
                (question.get_text(" ", strip=True), answer.find_all("a", href=True))
            )
    for heading in soup.find_all("h4"):
        links = []
        for sibling in heading.find_next_siblings():
            if sibling.name in ("h2", "h3", "h4"):
                break
            links.extend(sibling.find_all("a", href=True))
        blocks.append((heading.get_text(" ", strip=True), links))
    return blocks


@register_scraper
class StrathbogieScraper(BaseScraper):
    def __init__(self):
        super().__init__("strathbogie", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _meetings(soup: BeautifulSoup, page_url: str) -> list[tuple]:
        """(date, meeting type, agenda url, minutes url) per meeting."""
        meetings = []
        for heading, links in _blocks(soup):
            date = _heading_date(heading)
            if date is None:
                # "2026 Council Meeting Dates", "Register to Attend a Council
                # Meeting": information blocks, not meetings.
                continue
            papers: dict[str, list[str]] = {"agenda": [], "minutes": []}
            for link in links:
                href = urljoin(page_url, link["href"])
                if not href.lower().endswith(".pdf"):
                    continue
                kind = _kind(re.sub(r"\s+", " ", link.get_text(" ", strip=True)), href)
                if kind and href not in papers[kind]:
                    papers[kind].append(href)
            meeting_type = _meeting_type(heading)
            # "Extraordinary Council Meetings 29/06/2021" is one block for
            # two meetings held that day, each listed agenda then minutes,
            # so there the nth agenda goes with the nth minutes. Anywhere
            # else a block is one meeting, and its first agenda and first
            # minutes are the papers.
            count = (
                max(len(papers["agenda"]), len(papers["minutes"]))
                if re.search(r"\bmeetings\b", heading, re.IGNORECASE)
                else 1
            )
            for i in range(count):
                agenda = papers["agenda"][i] if i < len(papers["agenda"]) else None
                minutes = papers["minutes"][i] if i < len(papers["minutes"]) else None
                if agenda or minutes:
                    meetings.append((date, meeting_type, agenda, minutes))
        return meetings

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()

        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_MEETINGS_URL), "html.parser"
        )
        found = [(m, _MEETINGS_URL) for m in self._meetings(soup, _MEETINGS_URL)]
        if not found:
            # The page always carries several years of meetings, so finding
            # none means the layout changed, not that there is nothing.
            raise ValueError(
                f"{self.council_name}: no meetings found on {_MEETINGS_URL}"
            )

        if min(wanted) < min(m[0].year for m, _ in found):
            self.fetcher.sleep(_CRAWL_DELAY_SECONDS)
            archive = BeautifulSoup(
                self.fetcher.fetch_with_requests(_ARCHIVE_URL), "html.parser"
            )
            found += [(m, _ARCHIVE_URL) for m in self._meetings(archive, _ARCHIVE_URL)]

        results = []
        for (date, meeting_type, agenda, minutes), page_url in found:
            if date.year not in wanted:
                continue
            results.append(
                ScraperReturn(
                    name=meeting_type,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=page_url,
                    agenda_url=agenda,
                    minutes_url=minutes,
                    download_url=agenda or minutes,
                )
            )
        return results
