from council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
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

    def scraper(self) -> ScraperReturn:
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
            
        link = latest_meet.find_next("a")['href']
        download_url = f"{self.base_url}{link}"

        scraper_return = ScraperReturn(name, date, time, self.base_url, download_url)
        self.logger.info(f"""
            {scraper_return.name}
            {scraper_return.date}
            {scraper_return.time}
            {scraper_return.webpage_url}
            {scraper_return.download_url}"""
        )
        self.logger.info(f"{self.council_name} scraper finished successfully")
        return scraper_return

if __name__ == "__main__":
    scraper = CampbelltownScraper()  
    scraper.scraper()
