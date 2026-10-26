import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import (
    BROWSER_USER_AGENT,
    BaseScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.latrobe.vic.gov.au"
_LISTING_URL = f"{_BASE_URL}/Council/Our_Council/Minutes_and_Agendas"

# GovCMS (Drupal on amazee.io, behind Akamai and Signal Sciences). The listing
# is a view of every Council meeting since 2008, ten a page, each row a link
# to a page per meeting ("Council Meeting - 28 September 2026" ->
# /Council/Our_Council/Lists/Minutes_and_Agenda_Entry/CM_28_Sep_2026) whose
# Agenda and Minutes fields hold the PDFs. The view's "Contains" filter
# (`title=`) matches the year in the row title, so a year is one or two
# listing pages and then one request per meeting. Only Council meetings
# (ordinary, special, unscheduled) are listed; the council runs no planning
# committee.
_MAX_PAGES_PER_YEAR = 5

# Titles carry the date, sometimes with a stray comma ("Special Council
# Meeting -22 February, 2021"). The title is trusted over the page's Date
# field: on the 27 November 2025 mayoral election the field says 26 November
# while the title and both PDFs say 27.
_DATE = re.compile(
    r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*,?\s+(\d{4})\b",
    re.I,
)


@register_scraper
class LatrobeVicScraper(BaseScraper):
    # Refused from GitHub-hosted runners (403, 405 or a connection timeout,
    # measured 20 Oct 2026 by running every state shard from a runner) and
    # reachable from a home connection, so it goes through the residential
    # egress. See AGENTS.md, "Councils that block GitHub's runners".
    egress = "residential"

    # Signal Sciences holds the identifying User-Agent's connection open until
    # the read times out, on every page and on robots.txt; a browser-shaped
    # one gets 200 at once (measured 20 Oct 2026 from a home IP). Not yet
    # measured from a GitHub runner.
    user_agent = BROWSER_USER_AGENT

    # One full production year, measured 20 Oct 2026 from a home IP: 37 s
    # for 2025 (two listing pages and 18 meeting pages); 2026 so far is half
    # that. Orders dispatch only.
    expected_seconds = 37

    def __init__(self):
        super().__init__("latrobe_vic", "VIC", _BASE_URL)

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(set(years_filter))
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _year_rows(self, year: int) -> list[tuple[str, str]]:
        rows = []
        for page in range(_MAX_PAGES_PER_YEAR):
            url = f"{_LISTING_URL}?title={year}"
            if page:
                url += f"&page={page}"
            soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
            if not soup.find("form", id="views-exposed-form-minutes-and-agendas-page-1"):
                raise ValueError(f"No meetings view on {url}; the page has changed shape")
            for link in soup.find_all("a", href=True):
                if "/Lists/Minutes_and_Agenda_Entry/" in link["href"]:
                    title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
                    rows.append((title, urljoin(_BASE_URL, link["href"])))
            if not soup.find("a", href=f"?title={year}&page={page + 1}"):
                break
        return rows

    @staticmethod
    def _paper(soup: BeautifulSoup, field: str):
        block = soup.select_one(f".field--name-field-{field}")
        if not block:
            return None
        link = block.find("a", href=True)
        return urljoin(_BASE_URL, link["href"]) if link else None

    def _meeting(self, title: str, url: str, wanted: list[int]):
        match = _DATE.search(title)
        if not match:
            self.logger.warning(f"No date in listing title {title!r}; skipped")
            return None
        date = parse_date(" ".join(match.groups()), dayfirst=True).date()
        if date.year not in wanted:
            return None

        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        agenda_url = self._paper(soup, "agenda")
        minutes_url = self._paper(soup, "minutes")
        if not agenda_url and not minutes_url:
            if date < clock.today():
                self._past_bare += 1
            return None

        # "Council Meeting - 27 November 2025 (Mayoral Election)" ->
        # "Council Meeting (Mayoral Election)".
        name = (title[: match.start()] + " " + title[match.end():]).replace("–", "-")
        name = re.sub(r"\s+", " ", name).strip(" -")
        name = re.sub(r"\s+-\s*\(", " (", name).replace(" - ", " ").strip()

        return ScraperReturn(
            name=name or "Council Meeting",
            date=date.isoformat(),
            time=None,
            webpage_url=url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        results: list[ScraperReturn] = []
        seen = set()
        # Past meetings with papers, and past meetings whose page had none.
        past = 0
        self._past_bare = 0
        for year in wanted:
            for title, url in self._year_rows(year):
                if url in seen:
                    continue
                seen.add(url)
                meeting = self._meeting(title, url, wanted)
                if meeting is None:
                    continue
                past += meeting.date < clock.today().isoformat()
                results.append(meeting)

        # Past meetings have their papers posted, so rows that all came back
        # bare while past meetings were listed means the Agenda and Minutes
        # fields have changed shape, not that the council stopped publishing.
        if self._past_bare and past == 0:
            raise ValueError(
                f"{self._past_bare} past meetings in {wanted} but no papers on any of them"
            )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
