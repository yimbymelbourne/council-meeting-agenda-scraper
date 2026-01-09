from bs4 import BeautifulSoup
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from datetime import datetime
from urllib.parse import urljoin
import re

_STRATHFIELD_BASE_URL = "https://www.strathfield.nsw.gov.au"
_STRATHFIELD_MEETINGS_URL = urljoin(_STRATHFIELD_BASE_URL, "/council/council-meetings/")

_DOWNLOADS_SELECTOR = ".w-tabs-section > div > div > div > div > p > a"

_LINK_TEXT_REGEX = (
    r"(Council Meeting|Ordinary Council Meeting|Extraordinary Council Meeting)"
    r"\s+(\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})?"
    r"\s+\-\s+(Minutes|Agenda)"
)


@register_scraper
class StrathfieldNSWScraper(BaseScraper):
    current_year = int(datetime.today().strftime("%Y"))

    def __init__(self):
        super().__init__(
            council_name="strathfield", state="NSW", base_url=_STRATHFIELD_BASE_URL
        )

    def scraper(self) -> ScraperReturn:
        self.logger.info(f"Starting {self.council_name} scraper")

        url_segment = f"council-meetings-{self.current_year}"
        url = urljoin(_STRATHFIELD_MEETINGS_URL, url_segment)
        output = self.fetcher.fetch_with_selenium(url)
        soup = BeautifulSoup(output, "html.parser")

        for link_el in reversed(soup.select(_DOWNLOADS_SELECTOR)):
            match = re.match(_LINK_TEXT_REGEX, link_el.text)
            if not match:
                continue

            kind = match.group(1)
            date = match.group(2)
            link_kind = match.group(4)
            link = link_el["href"]

            if link_kind.lower() == "agenda":
                break
        else:
            raise ValueError(f"no links for {self.current_year}")

        name = f"{kind} {date}"
        self.logger.info(f"downloading: {name} {link}")

        return ScraperReturn(name, date, None, self.base_url, link)
