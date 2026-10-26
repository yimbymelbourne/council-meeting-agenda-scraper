import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://douglas.qld.gov.au"
_CURRENT_URL = f"{_BASE_URL}/council-meetings/"

# Douglas Shire (WordPress) keeps one page per financial year. The current
# page holds this financial year and the next, upcoming meetings included,
# and links each earlier year as "Douglas Shire Council Meeting Agenda &
# Minutes – 2024 -2025 Financial Year". Those slugs are irregular
# (/council-meetings-2021-22/, /council-meetings/agenda-minutes-2019-2020/),
# so they are read off the link text. A calendar year spans two financial
# years, and a production run (the current calendar year) is covered by the
# current page alone: 1 request.
#
# Each meeting is a toggle: an `h3.toggle-title` with the date and, for
# anything but an ordinary meeting, its kind ("Tuesday, 16 June 2026 -
# Special Budget Meeting"), then a panel of direct PDF links.
#
# The agenda is not one PDF. Douglas publishes it split by item: "1.
# Announcement and Table of Contents" (the cover, notice of meeting and
# contents—the first pages of the agenda), then one PDF per report ("7.1
# Mayor's Diary for June 2025"). The announcement is taken as the agenda,
# since it is the agenda's own front and lists every item; a single full
# agenda PDF wins where one is posted (17 June 2025). That is a few pages
# of an agenda that runs to 100-185 (the 30 July 2024 contents are "2 of
# 185"): the reports themselves are the per-item PDFs, which are not
# returned. A special meeting with no agenda posted but a "Notice of Special
# Council Meeting", which states the business, gets the notice (14 May
# 2024). Closed-session tables of contents are not the agenda.
#
# Minutes are chosen by link text. Confirmed minutes win over unconfirmed,
# and a minutes file whose YYYYMMDD name is another meeting's date is
# skipped: the 29 July 2025 panel also links "20260127-Ordinary-Council-
# Meeting-Unconfirmed-Minutes.pdf". Meetings from July 2019 to November
# 2019 link only an event page, not documents, so they are not returned;
# none is in range anyway.
#
# robots.txt (checked 20 Oct 2026) disallows nothing.

_FINANCIAL_YEAR = re.compile(r"(\d{4})\s*-\s*(\d{2,4})\s+Financial Year", re.IGNORECASE)
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october"
    "|november|december"
)
_HEADING_DATE = re.compile(rf"\b(\d{{1,2}})\s+({_MONTHS})\s+(\d{{4}})\b", re.IGNORECASE)
_FILE_STAMP = re.compile(r"^(20\d{2})(\d{2})(\d{2})-")

_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_NOT_MINUTES = re.compile(r"audio|recording", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_CLOSED = re.compile(r"closed session", re.IGNORECASE)
# "1. Announcement and Table of Contents", "Announcement & Table of
# Contents", "1. Announcment and Table of Contents".
_ANNOUNCEMENT = re.compile(r"announ\w*ment|table of contents", re.IGNORECASE)
# "Notice of Special Council Meeting" (14 May 2024): the one-page notice that
# states the business, posted where no agenda is. Not "Notice of Motion".
_NOTICE_OF_MEETING = re.compile(
    r"\bnotice of (?:special )?(?:council )?meeting\b", re.IGNORECASE
)
_UNCONFIRMED = re.compile(r"\bunconfirmed\b", re.IGNORECASE)
_ADJOURNED = re.compile(r"\badjourned\b", re.IGNORECASE)


def _heading_date(text: str) -> Optional[datetime.date]:
    match = _HEADING_DATE.search(text)
    if not match:
        return None
    month = _MONTHS.split("|").index(match[2].lower()) + 1
    try:
        return datetime.date(int(match[3]), month, int(match[1]))
    except ValueError:
        return None


def _meeting_name(heading: str, minutes_url: Optional[str]) -> str:
    """The kind of meeting, from its heading and its minutes' file name.

    Headings name anything but an ordinary meeting, mostly: "Tuesday 12
    August 2025" was a special meeting, and its minutes are filed as
    20250812-Special-Council-Meeting-Confirmed-Minutes.pdf; "Post Election
    Meeting" (9 April 2024) as ...-Statutory-Council-Meeting-...; the
    special meetings of 15 June 2021 and 25 June 2024 as Special-Budget.
    So the minutes' file name is read with the heading.
    """
    lowered = heading.lower()
    if minutes_url:
        lowered += " " + unquote(minutes_url.rsplit("/", 1)[-1]).lower().replace(
            "-", " "
        )
    if "budget" in lowered:
        return "Special Budget Meeting"
    if "statutory" in lowered:
        return "Statutory Council Meeting"
    if "special" in lowered:
        return "Special Council Meeting"
    return "Ordinary Council Meeting"


def _filed_for_another_day(href: str, date: datetime.date) -> bool:
    match = _FILE_STAMP.match(unquote(href.rsplit("/", 1)[-1]))
    if not match:
        return False
    try:
        return datetime.date(int(match[1]), int(match[2]), int(match[3])) != date
    except ValueError:
        return False


def _papers(panel, page_url: str, date: datetime.date) -> tuple:
    """The (agenda, minutes) URLs in one meeting's panel."""
    agendas: list[tuple[int, str]] = []
    minutes: list[tuple[int, str]] = []
    for link in panel.find_all("a", href=True):
        href = urljoin(page_url, link["href"])
        if not href.lower().endswith(".pdf"):
            continue
        text = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
        if _MINUTES.search(text) and not _NOT_MINUTES.search(text):
            if _filed_for_another_day(href, date):
                continue
            # The confirmed set, then unconfirmed; and the meeting's own
            # minutes before those of its adjourned sittings (30 April 2021).
            rank = (1 if _ADJOURNED.search(text) else 0) * 2 + (
                1 if _UNCONFIRMED.search(text) else 0
            )
            minutes.append((rank, href))
        elif _CLOSED.search(text):
            continue
        elif _AGENDA.search(text):
            agendas.append((0, href))
        elif _ANNOUNCEMENT.search(text):
            agendas.append((1, href))
        elif _NOTICE_OF_MEETING.search(text):
            agendas.append((2, href))
    agenda = min(agendas, key=lambda p: p[0])[1] if agendas else None
    minute = min(minutes, key=lambda p: p[0])[1] if minutes else None
    return agenda, minute


@register_scraper
class DouglasShireScraper(BaseScraper):
    def __init__(self):
        super().__init__("douglas", "QLD", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

    @staticmethod
    def _earlier_years(soup: BeautifulSoup) -> dict[int, str]:
        """Financial-year start -> page, for the years linked from the current page."""
        pages: dict[int, str] = {}
        for link in soup.find_all("a", href=True):
            match = _FINANCIAL_YEAR.search(link.get_text(" ", strip=True))
            if match:
                pages.setdefault(int(match[1]), urljoin(_CURRENT_URL, link["href"]))
        return pages

    @staticmethod
    def _meetings(soup: BeautifulSoup, page_url: str) -> list[tuple]:
        meetings = []
        for heading in soup.select("h3.toggle-title"):
            text = heading.get_text(" ", strip=True)
            date = _heading_date(text)
            panel = heading.find_next_sibling()
            if date is None or panel is None:
                continue
            agenda, minutes = _papers(panel, page_url, date)
            meetings.append((_meeting_name(text, minutes), date, agenda, minutes))
        return meetings

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        current = self._soup(_CURRENT_URL)
        pages = [(_CURRENT_URL, current)]
        earlier = self._earlier_years(current)
        if not earlier:
            # The current page always links the previous financial years, so
            # none means the layout changed.
            raise ValueError(
                f"{self.council_name}: no earlier financial years linked from {_CURRENT_URL}"
            )
        for start, url in sorted(earlier.items()):
            # A financial year starting in July `start` runs into `start + 1`.
            if start in wanted or start + 1 in wanted:
                pages.append((url, self._soup(url)))

        seen: set[tuple] = set()
        results = []
        for page_url, soup in pages:
            meetings = self._meetings(soup, page_url)
            if page_url == _CURRENT_URL and not meetings:
                # The current page always holds this financial year's
                # meetings, scheduled ones included, so no dated toggle means
                # the layout changed rather than an empty year.
                raise ValueError(
                    f"{self.council_name}: no dated meetings on {_CURRENT_URL}"
                )
            for name, date, agenda, minutes in meetings:
                # The 8 October 2024 special meeting's toggle is on its page
                # twice.
                if date.year not in wanted or (name, date) in seen:
                    continue
                if not agenda and not minutes:
                    # Scheduled meetings with nothing posted yet.
                    continue
                seen.add((name, date))
                results.append(
                    ScraperReturn(
                        name=name,
                        date=date.isoformat(),
                        time=None,
                        webpage_url=page_url,
                        agenda_url=agenda,
                        minutes_url=minutes,
                        download_url=agenda or minutes,
                    )
                )
        return results
