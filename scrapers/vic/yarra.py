import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from base_scraper import BaseScraper, register_scraper
from logging.config import dictConfig
from _dataclasses import ScraperReturn
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
import re


@register_scraper
class YarraScraper(BaseScraper):
    def __init__(self):
        council = "yarra"
        state = "VIC"
        base_url = "https://www.yarracity.vic.gov.au"
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn | None:
        self.logger.info(f"Starting {self.council_name} scraper")
        initial_webpage_url = "https://www.yarracity.vic.gov.au/about-us/council-and-committee-meetings/upcoming-council-and-committee-meetings"

        output = self.fetch_with_requests(initial_webpage_url)
        output = output.content
        print(output)


        name = None
        date = None
        time = None
        download_url = None
        agenda_link = None

        # finds agenda link
        initial_soup = BeautifulSoup(output, "html.parser")
        agenda_list = initial_soup.find('div', class_='show-for-medium-up')
        agenda_link = agenda_list.find('a')['href']
        agenda_output = self.fetch_with_requests(agenda_link)
        agenda_output = agenda_output.content

        # takes name, date, download url from agenda link
        soup = BeautifulSoup(agenda_output, "html.parser")

        name = soup.find('h1', class_='heading').text
        date = soup.find('p', class_='lead').text
        date = date.strip()
        download_url = soup.find('a', class_='download-link')['href']
        download_url = self.base_url + download_url

        scraper_return = ScraperReturn(name, date, time, self.base_url, download_url)

        self.logger.info(
            f"""
                    {scraper_return.name} 
                    {scraper_return.date} 
                    {scraper_return.time} 
                    {scraper_return.webpage_url} 
                    {scraper_return.download_url}"""
        )
        self.logger.info(f"{self.council_name} scraper finished successfully")
        return scraper_return


if __name__ == "__main__":
    scraper = YarraScraper()
    scraper.scraper()
