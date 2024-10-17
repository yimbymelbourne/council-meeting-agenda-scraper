from aus_council_scrapers.base import BaseScraper, register_scraper
from aus_council_scrapers.data import *
from bs4 import BeautifulSoup
import re
import datetime


@register_scraper
class CampbelltownScraper(BaseScraper):
    def __init__(self):
        council = "campbelltown"
        state = "NSW"
        base_url = "https://www.campbelltown.nsw.gov.au"
        super().__init__(council, state, base_url)
        self.default_location = (
            "Corner Queen and Broughton Streets, Campbelltown NSW 2560"
        )

    def scraper(self) -> Results:
        self.logger.info(f"Starting {self.council_name} scraper")

        name = None
        date = None
        time = "18:30"
        webpage_url = "https://www.campbelltown.nsw.gov.au/Council-and-Councillors/Meetings-and-Minutes"
        download_url = None

        year = datetime.date.today().year
        webpage_url += f"/{year}-Business-Papers#section-1"
        output = self.fetcher.fetch_with_requests(webpage_url)
        soup = BeautifulSoup(output, "html.parser")

        latest_meet = soup.find("h2")
        # Custom REGEX pattern as default date regex fails to matchS
        pattern = r"([a-zA-Z\s]+)(\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December))"
        match = re.match(pattern, latest_meet.text)
        if match:
            name = match.group(1).strip()
            date = match.group(2) + f" {year}"

        link = latest_meet.find_next("a")["href"]
        download_url = f"{self.base_url}{link}"

        yield ScraperResult.CouncilMeetingNotice(
            name,
            datetime=NoticeDate.FuzzyRaw(date, time),
            location=None,
            webpage_url=self.base_url,
            download_url=download_url,
        )


if __name__ == "__main__":
    scraper = CampbelltownScraper()
    scraper.scraper()
