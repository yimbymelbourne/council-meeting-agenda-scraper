from aus_council_scrapers.base import (
    BaseScraper,
    ScraperReturn,
    register_scraper,
    Fetcher,
)
from bs4 import BeautifulSoup
import re

from aus_council_scrapers.constants import TIME_REGEX


@register_scraper
class GlenEiraScraper(BaseScraper):
    def __init__(self):
        # Initialize with specific council information
        super().__init__("glen_eira", "VIC", "https://www.gleneira.vic.gov.au")
        self.default_location = "420 Glen Eira Road, Caulfield"

    def scraper(self) -> ScraperReturn | None:
        initial_webpage_url = f"https://www.gleneira.vic.gov.au/about-council/meetings-and-agendas/council-agendas-and-minutes"

        # Find next meeting url
        raw_html = self.fetcher.fetch_with_requests(initial_webpage_url)
        init_soup = BeautifulSoup(raw_html, "html.parser")
        meeting_a = init_soup.select_one("main a.listing")["href"]
        meeting_url = self.base_url + meeting_a

        # Parse html of next meeting
        meeting_html = self.fetcher.fetch_with_requests(meeting_url)
        meeting_soup = BeautifulSoup(meeting_html, "html.parser")

        # Extract different variables
        intro = meeting_soup.select_one("div#introduction").get_text()
        date_search = self.date_regex.search(intro)
        time_search = self.time_regex.search(intro)
        date = date_search.group() if date_search else None
        time = time_search.group() if time_search else None

        download_soup = meeting_soup.find(
            "a", href=re.compile(r"(.*).pdf", re.IGNORECASE)
        )
        download_url = self.base_url + download_soup["href"]

        return ScraperReturn(
            name=None,
            date=date,
            time=time,
            webpage_url=self.base_url,
            download_url=download_url,
            location=None,
        )


if __name__ == "__main__":
    scraper = GlenEiraScraper()
    result = scraper.scraper()
    print(result)
