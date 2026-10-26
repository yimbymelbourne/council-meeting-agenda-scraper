import datetime
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.westarthur.wa.gov.au"
# The home page carries the "Council Meetings <year>" menu, as every page
# does. It is read rather than any year's page because it is the one page
# that will not be renamed or dropped as years go by, so a production year
# costs two requests: this and that year's page.
_HUB_URL = f"{_BASE_URL}/"

# CouncilConnect CMS, but without its meetings module: each year is a
# hand-built content page holding one table, a row per meeting, with
# Meeting Date / Meeting Type / Agenda / Minutes / Other columns. The page
# URLs are irregular (2024 is council-meeting-dates.aspx, 2023 sits at the
# site root), so they are read from the menu rather than built. Pages begin
# in 2023; nothing earlier is published.
#
# Documents are /documents/<id>/<slug>, which serve the PDF inline. Late
# agendas and attachments are in the Other column and are not read.
_YEAR_LINK = re.compile(r"^Council Meetings (20\d\d)$")
_CONFIRMED = re.compile(r"(?<!un)confirmed", re.IGNORECASE)
_FIRST_YEAR = 2023

# A new year's page is added to the menu once the council makes it, and its
# first meeting may be weeks away, so early in a year an absent or empty
# page is expected. Either is an error only once this much of the year has
# passed, the rule CraftMeetingsModuleScraper uses.
_NEW_YEAR_GRACE_DAYS = 90


def _owed_papers(year: int) -> bool:
    """Whether a year has run long enough that it must have papers."""
    today = clock.today()
    return _FIRST_YEAR <= year < today.year or (
        year == today.year
        and (today - datetime.date(year, 1, 1)).days >= _NEW_YEAR_GRACE_DAYS
    )


@register_scraper
class WestArthurScraper(BaseScraper):
    def __init__(self):
        super().__init__("west_arthur", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _name(meeting_type: str) -> str:
        meeting_type = meeting_type.strip()
        if re.search(r"\bmeeting\b", meeting_type, re.IGNORECASE):
            return meeting_type
        if re.search(r"elector", meeting_type, re.IGNORECASE):
            return "Annual Electors Meeting"
        if re.search(r"audit|committee", meeting_type, re.IGNORECASE):
            return f"{meeting_type} Committee Meeting".replace(
                "Committee Committee", "Committee"
            )
        return f"{meeting_type} Council Meeting"

    @staticmethod
    def _link(cell, page_url: str):
        """The cell's document; confirmed minutes over unconfirmed ones."""
        links = [a for a in cell.find_all("a", href=True)] if cell else []
        if not links:
            return None
        labelled = [a for a in links if a.get_text(strip=True)] or links
        best = next(
            (a for a in labelled if _CONFIRMED.search(a.get_text())), labelled[0]
        )
        return urljoin(page_url, best["href"])

    def _year_page(self, year: int, url: str, html: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            header = [
                c.get_text(" ", strip=True).lower()
                for c in rows[0].find_all(["th", "td"])
            ]
            if "agenda" not in header or "minutes" not in header:
                continue
            column = {name: i for i, name in enumerate(header)}
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if len(cells) < len(header):
                    continue
                date_text = cells[column["meeting date"]].get_text(" ", strip=True)
                date_text = re.sub(r"[*]", "", date_text)
                if not re.search(r"20\d\d", date_text):
                    date_text = f"{date_text} {year}"
                try:
                    date = parse_date(date_text, fuzzy=True).date()
                except (ValueError, OverflowError):
                    continue
                agenda_url = self._link(cells[column["agenda"]], url)
                minutes_url = self._link(cells[column["minutes"]], url)
                if not agenda_url and not minutes_url:
                    # Future dates and cancelled meetings.
                    continue
                results.append(
                    ScraperReturn(
                        name=self._name(
                            cells[column["meeting type"]].get_text(" ", strip=True)
                        ),
                        date=date.isoformat(),
                        time=None,
                        webpage_url=url,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        hub_html = self.fetcher.fetch_with_requests(_HUB_URL)
        hub = BeautifulSoup(hub_html, "html.parser")
        year_pages = {}
        for link in hub.find_all("a", href=True):
            match = _YEAR_LINK.match(link.get_text(" ", strip=True))
            if match:
                year_pages.setdefault(
                    int(match.group(1)), urljoin(_HUB_URL, link["href"])
                )
        if not year_pages:
            raise RuntimeError(f"{self.council_name}: no year menu on {_HUB_URL}")

        missing = sorted(y for y in wanted if _owed_papers(y) and y not in year_pages)
        if missing:
            raise RuntimeError(
                f"{self.council_name}: no page in the menu on {_HUB_URL} for {missing}"
            )

        results = []
        for year in sorted(wanted & set(year_pages)):
            url = year_pages[year]
            found = self._year_page(year, url, self.fetcher.fetch_with_requests(url))
            if not found and _owed_papers(year):
                # Each year from 2023 had its first meeting by 23 February.
                raise RuntimeError(f"{self.council_name}: no papers on {url}")
            results.extend(found)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
