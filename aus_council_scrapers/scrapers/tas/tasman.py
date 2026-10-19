import datetime
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.tasman.tas.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/council/council-meetings/"

# Tasman Council (Tasmania). Not `tasman.infocouncil.biz`, which is Tasman
# District Council in New Zealand.
#
# One page holds the current year only: three download-list tables
# (Agendas, Council Meeting Recordings, Minutes), each row a file named
# "YYYYMMDD-Council-Meeting-Agenda-Month-YYYY.pdf". The page says earlier
# years' minutes are available only on request, so there is no archive to
# read. The tables look client-paged but every file is in the static HTML.
#
# The date prefix is the meeting date: it matches the dates in the 2026
# notice of meetings on the same page (25 March, not the 26 March on the
# audio file). The trailing month is checked against it, so a mistyped
# prefix is left out rather than filed under the wrong month.
#
# Only ordinary meetings are published here; the AGM is announced in the
# notice but has no papers on this page.
_PAPER = re.compile(
    r"/wp-content/uploads/(?P<date>\d{8})-Council-Meeting-(?P<kind>Agenda|Minutes)"
    r"-(?P<month>[A-Za-z]+)-(?P<year>\d{4})[^/]*\.pdf$",
    re.IGNORECASE,
)


@register_scraper
class TasmanScraper(BaseScraper):
    def __init__(self):
        super().__init__("tasman", "TAS", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser")

        tables = soup.select("table.fbdl-table")
        if not tables:
            # The page loaded but the download lists are gone: the layout has
            # changed, and an empty list would read as "no meetings".
            raise RuntimeError(
                f"{self.council_name}: no download-list tables at {_LISTING_URL}"
            )

        papers: dict[datetime.date, dict[str, str]] = {}
        unmatched: list[str] = []
        for table in tables:
            for link in table.find_all("a", href=True):
                url = urljoin(_LISTING_URL, link["href"].strip())
                match = _PAPER.search(url)
                if not match:
                    # The recordings table holds .mp3 and .mp4 files. A PDF
                    # here that the pattern misses is a renamed paper or a
                    # special meeting, so it is named in the log, not dropped
                    # quietly.
                    if urlparse(url).path.lower().endswith(".pdf"):
                        unmatched.append(url)
                    continue
                try:
                    meeting_date = datetime.datetime.strptime(
                        match["date"], "%Y%m%d"
                    ).date()
                except ValueError:
                    self.logger.warning(f"{self.council_name}: bad date in {url}")
                    continue
                named_month = match["month"].lower()
                if (
                    int(match["year"]) != meeting_date.year
                    or not meeting_date.strftime("%B").lower().startswith(named_month[:3])
                ):
                    self.logger.warning(
                        f"{self.council_name}: {url} names a different month from "
                        f"its date prefix; left out"
                    )
                    continue
                if meeting_date.year not in wanted:
                    continue
                kind = "minutes" if match["kind"].lower() == "minutes" else "agenda"
                papers.setdefault(meeting_date, {}).setdefault(kind, url)

        results = []
        for meeting_date in sorted(papers, reverse=True):
            found = papers[meeting_date]
            agenda_url = found.get("agenda")
            minutes_url = found.get("minutes")
            results.append(
                ScraperReturn(
                    name="Ordinary Council Meeting",
                    date=meeting_date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        for url in unmatched:
            self.logger.warning(
                f"{self.council_name}: {url} is in the download lists but not named "
                f"YYYYMMDD-Council-Meeting-Agenda|Minutes-Month-YYYY.pdf; left out"
            )
        if not results:
            # The page holds the current year only, so a past year legitimately
            # finds nothing, and before March the year's first paper may not be
            # up. Otherwise an empty list means the files were renamed or the
            # page changed, and returning [] would read downstream as a night
            # with no meetings.
            today = clock.today()
            if unmatched or (
                today.year in wanted and today.month >= 3
            ):
                raise RuntimeError(
                    f"{self.council_name}: no papers matched for {sorted(wanted)} at "
                    f"{_LISTING_URL} ({len(unmatched)} PDFs did not match the naming)"
                )
            self.logger.warning(
                f"{self.council_name}: no papers for {sorted(wanted)} at {_LISTING_URL}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
