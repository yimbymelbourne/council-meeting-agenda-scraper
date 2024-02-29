from council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from bs4 import BeautifulSoup
import re

@register_scraper
class CamdenScraper(BaseScraper):
    def __init__(self):
        council = "camden"
        state = "NSW"
        base_url = "https://www.camden.nsw.gov.au"
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn:
        self.logger.info(f"Starting {self.council_name} scraper")

        name = None
        date = None
        time = "18:30"
        webpage_url = "https://www.camden.nsw.gov.au/council/council-meetings"
        download_url = None

        output = self.fetcher.fetch_with_requests(webpage_url)
        soup = BeautifulSoup(output, "html.parser")
        meets = soup.find("h4")
        link = meets.find_next("a")['href']
        latest_year = f"{self.base_url}/" + link

        output = self.fetcher.fetch_with_requests(latest_year)
        soup = BeautifulSoup(output, "html.parser")

        latest_meet = soup.find("h2")
        # Custom pattern. TODO: Refactor to use constant regex.
        pattern = r"(\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})(\s[a-zA-Z\(\)]+)?"
        match = re.match(pattern, latest_meet.text)
        if match:
            if "Extraordinary" in latest_meet.text:
                name = "Extraordinary Council Meeting"
            else:
                name = "Council Meeting"
            date = match.group(1)

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
    scraper = CamdenScraper()  
    scraper.scraper()
