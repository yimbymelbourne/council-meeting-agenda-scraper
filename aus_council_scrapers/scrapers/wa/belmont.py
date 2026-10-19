import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.belmont.wa.gov.au"
_INDEX_URL = (
    "https://www.belmont.wa.gov.au/About-Us/Our-Council/All-about-Council"
    "/Council-meetings/Agendas-and-Minutes"
)
_LISTING_URL = _INDEX_URL + "/Ordinary-and-Special-Council-Meetings"

# Belmont (Kentico) has a page per meeting category. Three are read:
#
# * Ordinary and Special Council Meetings, and Committees (the audit
#   committee, and until mid-2025 the executive and standing committees).
#   Each category page holds the current year, and each earlier year back to
#   2021 is a page of its own, linked from a box labelled with the bare year.
#   Those slugs are irregular (`-2025`, `-4` for 2024, `-3` for 2023, `-1`
#   for 2022, `-2021`; `committees-3` for 2024), so they are read off the
#   labels rather than built. Older records exist only in the council's
#   records search, which is not scraped.
# * Annual and Special Electors' Meetings: a single page, every year on it.
#
# Two are not. Agenda Briefing Forums publish a "Matrix" and "Programme" per
# forum, not an agenda or minutes. The Belmont Trust page lists no meeting
# documents.
#
# So a one-year production run costs three requests: the two category pages
# that hold the current year, and the electors' page.
#
# Each page groups documents in accordions headed by a date or a committee,
# linking `/docs/ecm/<Title-Slug>`—a stable URL that serves the PDF itself.
# The accordion is not a reliable key for the meeting: the 10 June 2026
# special meeting's panel also carries the 23 June ordinary meeting's second
# amended agenda. Every document title names its meeting, though—"Ordinary
# Council Meeting 24 February 2026 Amended Agenda"—so meetings are keyed off
# that.
_CATEGORIES = (
    # (category page, whether earlier years are on year pages of their own)
    (_LISTING_URL, True),
    (_INDEX_URL + "/Committees", True),
    (_INDEX_URL + "/Annual-and-Special-Electors-Meetings", False),
)

_YEAR_LINK = re.compile(r"^\s*(\d{4})\s*$")
# The year a category page holds, from its heading: "2026 Agendas and
# Minutes" for council meetings, "2026 Minutes" for committees.
_PAGE_YEAR = re.compile(r"^\s*(\d{4})\s+(?:Agendas and\s+)?Minutes\b", re.IGNORECASE)
_TITLE = re.compile(
    r"^(?P<name>.+?)\s+(?P<date>\d{1,2}\s+[A-Za-z]+\s+\d{4})\s+(?P<kind>.+?)\s*$"
)
# A few titles put the document type before the date: "Standing Committee
# (Audit and Risk) Minutes 14 February 2022 Confirmed".
_KIND_IN_NAME = re.compile(r"\s+(agenda|minutes)$", re.IGNORECASE)
# Hand-typed titles spell one meeting type several ways, and each is put
# back to one name: "Annual Electors- Meeting" and "Annual Electors Meeting"
# (a mangled or missing apostrophe), "Audit Risk and Improvement Committee"
# (a dropped comma), "Standing Committee (Audit and Risk) Meeting".
_NAME_FIXES = (
    (re.compile(r"\bElectors-?(?=\s)"), "Electors'"),
    (re.compile(r"\bAudit Risk\b"), "Audit, Risk"),
    (re.compile(r"\)\s+Meeting$"), ")"),
)

# A meeting can carry an agenda, an amended agenda and a second amended
# agenda. Each amendment is a full reissue of the agenda—the 24 February
# 2026 agenda is 58.6 MB and its amended agenda 56.0 MB—not a supplement,
# so the latest one is the meeting's agenda. Minutes go from unconfirmed to
# confirmed once the next meeting adopts them; the confirmed set wins.
# Audio recordings are neither.
_AGENDA_RANK = {
    "second amended agenda": 0,
    "amended agenda": 1,
    "agenda": 2,
}
_MINUTES_RANK = {
    "minutes confirmed": 0,
    "minutes": 0,
    # "Special Standing Committee (Community Vision) 18 October 2021
    # Confirmed"—the confirmed minutes, with the word "Minutes" left out.
    "confirmed": 0,
    "amended minutes unconfirmed": 1,
    "minutes unconfirmed": 2,
}


@register_scraper
class BelmontScraper(BaseScraper):
    def __init__(self):
        council = "belmont"
        state = "WA"
        base_url = _BASE_URL
        super().__init__(council, state, base_url)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _year_pages(soup: BeautifulSoup, page_url: str) -> dict[int, str]:
        pages: dict[int, str] = {}
        for link in soup.find_all("a", href=True):
            match = _YEAR_LINK.match(link.get_text(" ", strip=True))
            if match:
                pages.setdefault(int(match.group(1)), urljoin(page_url, link["href"]))
        return pages

    @staticmethod
    def _page_year(soup: BeautifulSoup) -> Optional[int]:
        """The year a category page holds, from its heading."""
        for heading in soup.find_all("h2"):
            match = _PAGE_YEAR.match(heading.get_text(" ", strip=True))
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _key(name: str, date) -> tuple:
        # Punctuation and case are left out of the key as well, so a
        # spelling the name fixes miss still pairs a meeting's agenda with its
        # minutes rather than splitting them over two records.
        return (re.sub(r"[^a-z0-9]", "", name.lower()), date)

    def _meetings(
        self, soup: BeautifulSoup, page_url: str, wanted: set[int]
    ) -> list[ScraperReturn]:
        meetings: dict[tuple, dict] = {}
        for content in soup.select("div.accordion-content"):
            for link in content.select('a[href*="/docs/ecm/"]'):
                title = link.select_one(".document-title")
                text = re.sub(r"\s+", " ", (title or link).get_text(" ", strip=True))
                match = _TITLE.match(text)
                if not match:
                    continue
                name = match.group("name")
                kind = match.group("kind").lower()
                moved = _KIND_IN_NAME.search(name)
                if moved:
                    name = name[: moved.start()]
                    kind = f"{moved.group(1).lower()} {kind}"
                if kind in _AGENDA_RANK:
                    field, rank = "agenda", _AGENDA_RANK[kind]
                elif kind in _MINUTES_RANK:
                    field, rank = "minutes", _MINUTES_RANK[kind]
                else:
                    continue
                try:
                    date = parse_date(match.group("date"), dayfirst=True).date()
                except (ValueError, OverflowError):
                    continue
                if date.year not in wanted:
                    continue

                for pattern, replacement in _NAME_FIXES:
                    name = pattern.sub(replacement, name)
                meeting = meetings.setdefault(
                    self._key(name, date),
                    {"name": name, "date": date, "agenda": None, "minutes": None},
                )
                current = meeting[field]
                if current is None or rank < current[0]:
                    meeting[field] = (rank, urljoin(page_url, link["href"]))

        results = []
        for papers in meetings.values():
            agenda_url = papers["agenda"][1] if papers["agenda"] else None
            minutes_url = papers["minutes"][1] if papers["minutes"] else None
            results.append(
                ScraperReturn(
                    name=papers["name"],
                    date=papers["date"].isoformat(),
                    time=None,
                    webpage_url=page_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return results

    def _category_pages(self, url: str, by_year: bool, wanted: set[int]):
        """Yield (page URL, soup) for each of a category's pages worth reading."""
        landing = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        if not by_year:
            yield url, landing
            return

        landing_year = self._page_year(landing)
        if landing_year is None:
            # Without its heading there is no telling which year the landing
            # page holds, so its meetings—the current year's—are lost.
            self.logger.warning(
                f"No '<year> Minutes' heading on {url}; the current year "
                "cannot be read"
            )
        elif landing_year in wanted:
            yield url, landing
        for year, page_url in sorted(
            self._year_pages(landing, url).items(), reverse=True
        ):
            if year in wanted and year != landing_year:
                yield page_url, None

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        results: list[ScraperReturn] = []
        seen: set[tuple] = set()
        # A page that cannot be fetched is logged and skipped. But if nothing
        # at all comes back and a fetch failed, the failure is raised:
        # returning [] would report a blocked or down site as a council with
        # no meetings.
        last_error: Optional[Exception] = None
        for category_url, by_year in _CATEGORIES:
            try:
                pages = list(self._category_pages(category_url, by_year, wanted))
            except Exception as e:
                last_error = e
                self.logger.warning(f"Could not read {category_url}: {e}")
                continue
            for url, soup in pages:
                if soup is None:
                    try:
                        soup = BeautifulSoup(
                            self.fetcher.fetch_with_requests(url), "html.parser"
                        )
                    except Exception as e:
                        last_error = e
                        self.logger.warning(f"Could not read {url}: {e}")
                        continue
                for meeting in self._meetings(soup, url, wanted):
                    # A misfiled document can put a meeting on a neighbouring
                    # year's page as well; the first page to list it keeps it.
                    key = self._key(meeting.name, meeting.date)
                    if key not in seen:
                        seen.add(key)
                        results.append(meeting)

        if not results and last_error is not None:
            raise last_error
        if not results:
            self.logger.warning(f"{self.council_name} scraper found no meetings")
        else:
            self.logger.info(
                f"{self.council_name} scraper found {len(results)} meetings"
            )
        return results
