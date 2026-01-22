from aus_council_scrapers.base import (
    BaseScraper,
    ScraperReturn,
    register_scraper,
    Fetcher,
)
from bs4 import BeautifulSoup
import re

# Match any agenda with a pdf extension
AGENGA_HREF_REGEX = re.compile(r"(.*)Agenda(.*)\.pdf", re.IGNORECASE)


@register_scraper
class DarebinScraper(BaseScraper):

    def __init__(self):
        super().__init__(f"darebin", "VIC", "https://www.darebin.vic.gov.au")
        self.date_pattern = re.compile(
            r"\b(\d{1,2})\s(January|February|March|April|May|June|July|August|September|October|November|December)\s(\d{4})\b"
        )
        self.default_location = "Council Chamber, 350 High Street, Preston."
        self.default_time = "18:00"

    def scraper(self) -> list[ScraperReturn]:
        # Get page
        webpage_url = "https://www.darebin.vic.gov.au/About-Council/Council-structure-and-performance/Council-and-Committee-Meetings/Council-meetings/Meeting-agendas-and-minutes/2024-Council-meeting-agendas-and-minutes"
        output = self.fetcher.fetch_with_requests(webpage_url)

        # Feed the HTML to BeautifulSoup
        soup = BeautifulSoup(output, "html.parser")

        # look for the first a tag with the word agenda
        target_a_tag = soup.find("a", href=AGENGA_HREF_REGEX)
        self.logger.debug(f"Target a tag: {target_a_tag}")

        # Print the result
        if not target_a_tag:
            raise RuntimeError("No agenda found")

        #  Extract the download url
        download_url = self.base_url + target_a_tag.get("href")
        self.logger.debug(f"Download URL: {download_url}")

        # get the text inside that first name tag - contains both the name of the meeting and the date
        txt_value = target_a_tag.get_text()
        self.logger.debug(f"Agenda text value {txt_value}")

        date_str: str = None
        if txt_value:
            # extract the date from txt_value
            date_str = self.date_pattern.search(txt_value).group()
            self.logger.debug(f"Date string: {date_str}")

        return [ScraperReturn(
            name=None,
            date=date_str,
            time=None,
            webpage_url=webpage_url,
            download_url=download_url,
        )]


if __name__ == "__main__":
    scraper = DarebinScraper()
    scraper.scraper()
