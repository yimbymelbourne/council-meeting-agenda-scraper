import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_LISTING_URL = (
    "https://www.ryde.nsw.gov.au"
    "/Council/Council-Meetings/Council-Meeting-agendas-and-minutes"
)

# The listing is an ASP.NET results grid, ten meetings a page, newest first.
# It has no page query parameter — paging is a form post — but the non-JS
# controls accept a page number directly, so page one's hidden fields are
# enough to jump to any page.
_PAGE_SELECT = "ctl11$ctl00$ctl07"
_PAGE_SUBMIT = "ctl11$ctl00$ctl08"

# Only the meeting's own page carries the document links, and its naming has
# changed over the years ("...-agenda.pdf" then "agenda-...pdf"), so they have
# to be read rather than constructed.
_DOCUMENT_TITLES = {"agenda": "agenda_url", "minutes": "minutes_url"}


@register_scraper
class RydeScraper(BaseScraper):
    def __init__(self):
        council = "ryde"
        state = "NSW"
        base_url = "https://www.ryde.nsw.gov.au"
        super().__init__(council, state, base_url)
        self.default_location = "Level 1A, 1 Pope Street, Ryde"
        self.default_time = "6:00 PM"

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _form_fields(soup: BeautifulSoup) -> dict[str, str]:
        """Page one's hidden form state, needed to post for any other page."""
        form = soup.find("form")
        if not form:
            return {}
        return {
            field["name"]: field.get("value") or ""
            for field in form.find_all("input", type="hidden")
            if field.get("name")
        }

    @staticmethod
    def _page_count(soup: BeautifulSoup) -> int:
        select = soup.find("select", attrs={"name": _PAGE_SELECT})
        if not select:
            return 1
        pages = [
            int(option["value"])
            for option in select.find_all("option")
            if (option.get("value") or "").isdigit()
        ]
        return max(pages) if pages else 1

    def _listed_meetings(self, soup: BeautifulSoup) -> list[tuple[int, str, str]]:
        """Return (year, listing title, meeting page url) for one listing page."""
        meetings = []
        for article in soup.find_all("article"):
            link = article.find("a", href=True)
            heading = article.find(["h3", "h2"])
            if not link or not heading:
                continue

            title = re.sub(r"\s+", " ", heading.get_text(" ", strip=True))
            date_match = self.date_regex.search(title)
            if not date_match:
                continue

            year = parse_date(date_match.group(), dayfirst=True).year
            meetings.append((year, title, urljoin(_LISTING_URL, link["href"])))
        return meetings

    def _meeting(self, url: str, title: str) -> ScraperReturn:
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

        documents = {}
        for link in soup.find_all("a", href=True):
            # Mayoral minutes are titled with their own file name and would
            # otherwise be matched as the meeting's minutes.
            key = (link.get("title") or "").strip().lower()
            field = _DOCUMENT_TITLES.get(key)
            if field and field not in documents:
                documents[field] = urljoin(url, link["href"])

        if not documents:
            # Listed ahead of its papers being published.
            return None

        heading = soup.find("h1", class_="oc-page-title")
        heading_text = (
            re.sub(r"\s+", " ", heading.get_text(" ", strip=True)) if heading else title
        )
        date_match = self.date_regex.search(heading_text) or self.date_regex.search(
            title
        )
        name = self.date_regex.sub("", heading_text).strip(" -–—")

        agenda_url = documents.get("agenda_url")
        minutes_url = documents.get("minutes_url")
        return ScraperReturn(
            name=name or "Council Meeting",
            date=date_match.group(),
            time=None,
            webpage_url=url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        wanted = self._wanted_years()
        earliest_wanted = min(wanted)

        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser"
        )
        fields = self._form_fields(soup)
        page_count = self._page_count(soup)

        listed: list[tuple[int, str, str]] = []
        for page in range(1, page_count + 1):
            if page > 1:
                soup = BeautifulSoup(
                    self.fetcher.fetch_with_requests(
                        _LISTING_URL,
                        method="POST",
                        data={
                            **fields,
                            _PAGE_SELECT: str(page),
                            _PAGE_SUBMIT: "Go",
                        },
                    ),
                    "html.parser",
                )

            on_page = self._listed_meetings(soup)
            listed.extend(m for m in on_page if m[0] in wanted)
            years = {year for year, _, _ in on_page}
            self.logger.debug(f"page {page}: {len(on_page)} listed {sorted(years)}")

            # Newest first, so a page entirely older than what we asked for
            # means the pages behind it are older still.
            if years and max(years) < earliest_wanted:
                break

        results = []
        for _, title, url in listed:
            try:
                meeting = self._meeting(url, title)
            except Exception as e:
                self.logger.warning(f"Could not read {url}: {e}")
                continue
            if meeting:
                results.append(meeting)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
