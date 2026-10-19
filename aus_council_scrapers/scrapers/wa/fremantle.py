import html
import json
import re

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.fremantle.wa.gov.au"
_LISTING_URL = f"{_BASE_URL}/your-city-and-council/about-council/agendas-and-minutes/"

# The listing page is a shell filled by the theme's page-type-listing script,
# which POSTs its filters to this endpoint. Each result in `data[]` is one
# meeting, carrying its title ("Ordinary Meeting of Council, 23 September
# 2026"), its date, a permalink and a `template` of accordion HTML holding
# the documents. (The core /wp-json/wp/v2/ route for the same post type
# exposes the posts but not the documents.)
_API_URL = f"{_BASE_URL}/wp-json/aw/v1/minutes-and-agendas"

# The year filter is the listing's own: a LIKE match on the meeting date, so
# one request returns one year's meetings, upcoming ones included. Unfiltered,
# the same endpoint returns everything since 2019 in one 3 MB response; per
# year is the same total for the full history and a tenth of it in
# production, which only ever asks for one year.
_PAGE_SIZE = 500

# Each meeting's documents sit in sections headed "Agenda", "Minutes",
# "Meeting attachments", "Supporting documents" and "Minutes (YouTube)".
# Only the first two are the meeting's agenda and minutes; the YouTube
# section is a live-stream link.
_SECTIONS = {"agenda": "agenda", "minutes": "minutes"}


@register_scraper
class FremantleScraper(BaseScraper):
    def __init__(self):
        super().__init__("fremantle", "WA", _BASE_URL)

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(years_filter)
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _search(self, year: int) -> list[dict]:
        body = {
            "post_type": "minutes-and-agendas",
            "SI": "minutes-and-agendas",
            "OB": "",
            "Q": "",
            "PS": _PAGE_SIZE,
            "PG": 1,
            "PR": [
                {
                    "OR": True,
                    "key": "year",
                    "operater": "like",
                    "values": [{"value": str(year)}],
                }
            ],
        }
        response = self.fetcher.fetch_with_requests(_API_URL, method="POST", json=body)
        meetings = json.loads(response).get("data") or []
        if len(meetings) >= _PAGE_SIZE:
            self.logger.warning(
                f"{year} returned a full page of {_PAGE_SIZE}; later meetings may be missing"
            )
        return meetings

    @staticmethod
    def _documents(template: str) -> dict[str, str]:
        soup = BeautifulSoup(template or "", "html.parser")
        found = {}
        for row in soup.select(".agendas-row"):
            heading = row.select_one(".agendas--heading")
            kind = (
                _SECTIONS.get(heading.get_text(" ", strip=True).lower())
                if heading
                else None
            )
            link = row.select_one(".agendas--body a[href]")
            if kind and link and kind not in found:
                found[kind] = link["href"]
        return found

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        results = []
        errors: list[Exception] = []
        for year in self._wanted_years():
            try:
                meetings = self._search(year)
            except Exception as e:
                self.logger.warning(f"Could not read {year}: {e}")
                errors.append(e)
                continue

            for meeting in meetings:
                date = parse_date(meeting["Date"], dayfirst=True).date()
                if date.year != year:
                    continue
                documents = self._documents(meeting.get("template"))
                agenda_url = documents.get("agenda")
                minutes_url = documents.get("minutes")
                if not agenda_url and not minutes_url:
                    continue

                # Titles are "<meeting type>, <date>"; one older title uses an
                # en dash (as an HTML entity) in place of the comma.
                title = html.unescape(meeting.get("title") or "")
                name = re.sub(
                    r"\s*[,–—-]?\s*" + re.escape(meeting["Date"]) + r"\s*$", "", title
                )

                results.append(
                    ScraperReturn(
                        name=name.strip(" ,–—-") or "Council Meeting",
                        date=date.isoformat(),
                        time=None,
                        webpage_url=meeting.get("permalink") or _LISTING_URL,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )

        # Production asks for one year, so one failed fetch can leave
        # nothing. An empty list does not raise, and main.py would count the
        # council as working with 0 meetings. Raise instead; a failure that
        # still leaves other years' meetings stays a warning.
        if not results and errors:
            raise errors[-1]
        if not results:
            self.logger.warning(f"{self.council_name}: no meetings found")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
