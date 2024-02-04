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
class ManninghamScraper(BaseScraper):
    def __init__(self):
        council = "manningham"
        state = "VIC"
        base_url = ""
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn | None:
        # self.logger.info(f"Starting {self.council_name} scraper")

        self.logger.error(f"{self.council_name} is without a Scraper, Can you Help!")
        return None
        """
        YOUR CODE HERE
        """

        # scraper_return = ScraperReturn(name, date, time, self.base_url, download_url)

        # self.logger.info(f"""
        #     {scraper_return.name}
        #     {scraper_return.date}
        #     {scraper_return.time}
        #     {scraper_return.webpage_url}
        #     {scraper_return.download_url}"""
        # )
        # self.logger.info(f"{self.council_name} scraper finished successfully")
        # return scraper_return


if __name__ == "__main__":
    scraper = ManninghamScraper()
    scraper.scraper()
