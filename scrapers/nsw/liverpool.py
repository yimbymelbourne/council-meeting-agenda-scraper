import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from base_scraper import BaseScraper, register_scraper
from logging.config import dictConfig
from _dataclasses import ScraperReturn
from bs4 import BeautifulSoup
import re


@register_scraper
class LiverpoolScraper(BaseScraper):
    def __init__(self):
        council = "liverpool"
        state = "NSW"
        base_url = "https://www.liverpool.nsw.gov.au"
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn:
        self.logger.info(f"Starting {self.council_name} scraper")
                
        name = None
        date = None
        time = None
        webpage_url = "https://liverpool.infocouncil.biz/"
        download_url = None

        output = self.fetch_with_requests(webpage_url)
        soup = BeautifulSoup(output.content, "html.parser")

        date = soup.find("td", class_ = "bpsGridDate").text
        name = soup.find("td", class_ = "bpsGridCommittee").contents[0].strip()
        link = soup.find("a", class_ = "bpsGridPDFLink")["href"]
        download_url = f"{webpage_url}{link}"

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
    scraper = LiverpoolScraper()
    scraper.scraper()
