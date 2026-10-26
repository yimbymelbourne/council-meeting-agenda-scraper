import re
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.mandurah.wa.gov.au"

# Two server-rendered Kentico Xperience pages: the current year, and every
# year from 2020 to last year on a separate "historic" page (1.1 MB). Each
# year is an accordion section; each item in it is one meeting, headed
# "27 October 2026 - Ordinary Council Meeting", holding download buttons.
#
# The historic page's address really does contain spaces.
_CURRENT_URL = f"{_BASE_URL}/our-council/council-meetings/agendas-and-minutes"
_HISTORIC_URL = (
    f"{_BASE_URL}/our-council/council-meetings/agendas%20and%20minutes%20historic"
)

# Alongside the agenda and minutes each meeting carries its supporting
# papers—the monthly schedule of accounts, finance presentations, late
# items, "additional information" reports—several of which have "Agenda"
# in their label ("Council Meeting Agenda Feb 25 - Schedule of Accounts Dec
# 2024"). Labels are hand-typed and vary by year ("Council Meeting Agenda
# Jun 24", "Ordinary Council Meeting - Agenda - 27 October 2026"). One
# agenda is "Council Meeting Agenda Jun 22 incl Schedule of Accounts May
# 2021"—the agenda itself, with the schedule bound in.
_NOT_AGENDA_OR_MINUTES = re.compile(
    r"presentation|(?<!incl )(?<!including )schedule of accounts"
    r"|additional information|attach|late item|revised|annual report",
    re.IGNORECASE,
)
_KIND = re.compile(r"\b(agenda|minutes)\b", re.IGNORECASE)
_PART = re.compile(r"\bpart\s*0?(\d)", re.IGNORECASE)
_SUPERSEDED = re.compile(r"\b(?:updated|amended)\b", re.IGNORECASE)
_HEADING = re.compile(r"^\s*(\d{1,2}\s+\w+\s+\d{4})\s*[-–—]\s*(.+?)\s*$")


def _absolute(href: str) -> str:
    """Resolve the link and percent-encode the spaces in its file name."""
    parts = urlsplit(urljoin(_BASE_URL, href))
    return urlunsplit(parts._replace(path=quote(parts.path, safe="/%")))


@register_scraper
class MandurahScraper(BaseScraper):
    def __init__(self):
        super().__init__("mandurah", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _rank(label: str) -> int:
        # Prefer the original over an updated reissue, and part 1 of a split
        # agenda (which opens with the business of the meeting) over later
        # parts.
        part = _PART.search(label)
        return (int(part.group(1)) - 1 if part else 0) + (
            1 if _SUPERSEDED.search(label) else 0
        )

    def _meetings(self, url: str, wanted: set[int]) -> list[ScraperReturn]:
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        sections = soup.select("[id^=AccordionSection]")
        if not sections:
            self.logger.warning(
                f"No year sections on {url}; the page layout may have changed"
            )

        meetings = []
        for section in sections:
            for item in section.find_all(attrs={"data-accordion-wrapper": True}):
                trigger = item.find(attrs={"data-accordion-trigger": True})
                heading = (
                    re.sub(r"\s+", " ", trigger.get_text(" ", strip=True))
                    if trigger
                    else ""
                )
                match = _HEADING.match(heading)
                if not match:
                    continue
                date = parse_date(match.group(1), dayfirst=True).date()
                if date.year not in wanted:
                    continue

                best: dict[str, tuple[int, str]] = {}
                for link in item.find_all("a", href=True):
                    label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
                    if _NOT_AGENDA_OR_MINUTES.search(label):
                        continue
                    # "Council Meeting Agenda 22 February Part 01 - Minutes"
                    # is the agenda's first part, which opens with the last
                    # meeting's minutes; the word that comes first decides.
                    kind = _KIND.search(label)
                    if not kind:
                        continue
                    kind = kind.group(1).lower()
                    rank = self._rank(label)
                    if kind not in best or rank < best[kind][0]:
                        best[kind] = (rank, _absolute(link["href"]))

                agenda_url = best.get("agenda", (None, None))[1]
                minutes_url = best.get("minutes", (None, None))[1]
                if not agenda_url and not minutes_url:
                    continue
                meetings.append(
                    ScraperReturn(
                        name=match.group(2),
                        date=date.isoformat(),
                        time=None,
                        webpage_url=url,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )
        return meetings

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # The current page always: it holds this year and anything upcoming.
        # The historic page only when an earlier year is wanted—never in
        # production, which asks for the current year alone.
        pages = [_CURRENT_URL]
        if min(wanted) < clock.current_year():
            pages.append(_HISTORIC_URL)

        results: dict[tuple, ScraperReturn] = {}
        errors: list[Exception] = []
        for url in pages:
            try:
                meetings = self._meetings(url, wanted)
            except Exception as e:
                self.logger.warning(f"Could not read {url}: {e}")
                errors.append(e)
                continue
            for meeting in meetings:
                # At the turn of the year a meeting can sit on both pages.
                results.setdefault((meeting.name, meeting.date), meeting)

        meetings = list(results.values())
        # Production asks for one year, so one failed fetch can leave
        # nothing. An empty list does not raise, and main.py would count the
        # council as working with 0 meetings. Raise instead; a failure that
        # still leaves other years' meetings stays a warning.
        if not meetings and errors:
            raise errors[-1]
        if not meetings:
            self.logger.warning(f"{self.council_name}: no meetings found")
        self.logger.info(f"{self.council_name} scraper found {len(meetings)} meetings")
        return meetings
