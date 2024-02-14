from council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from bs4 import BeautifulSoup
import re


@register_scraper
class StonningtonScraper(BaseScraper):
    def __init__(self):
        council = "stonnington"
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
        #     {scraper_return.time}
        #     {scraper_return.date}
        #     {scraper_return.webpage_url}
        #     {scraper_return.download_url}"""
        # )
        # self.logger.info(f"{self.council_name} scraper finished successfully")
        # return scraper_return
