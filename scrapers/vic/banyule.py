import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from base_scraper import BaseScraper, register_scraper
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

from logging.config import dictConfig
from _dataclasses import ScraperReturn
from bs4 import BeautifulSoup
import re


@register_scraper
class BanyuleScraper(BaseScraper):
    def __init__(self):
        council = "banyule"
        state = "VIC"
        base_url = "https://www.banyule.vic.gov.au"
        super().__init__(council, state, base_url)
        self.time_pattern = re.compile(r"\d+:\d+\s?[apmAPM]+")

    def scraper(self) -> ScraperReturn | None:
        base_url = "https://www.banyule.vic.gov.au"
        webpage_url = "https://www.banyule.vic.gov.au/About-us/Councillors-and-Council-meetings/Council-meetings/Council-meeting-agendas-and-minutes"

        chrome_options = Options()
        chrome_options.add_argument("--headless")
        driver = webdriver.Chrome(options=chrome_options)

        name = None
        date = None
        time = None
        page_url = None
        download_url = None

        # Get the index page to find all available meeting pages
        driver.get(webpage_url)
        main_output = driver.page_source

        main_soup = BeautifulSoup(main_output, "html.parser")
        links = main_soup.find_all("a", class_="accordion-trigger")

        for link in links:
            # Navigate to each linked page and look an agenda to download
            page_url = link.get("href")

            driver.get(page_url)
            page_output = driver.page_source
            page_soup = BeautifulSoup(page_output, "html.parser")

            # Find meeting details
            name_element = page_soup.select("ul.minutes-details-list li:nth-of-type(2) .field-value")[0]
            name = name_element and name_element.text
            date_element = page_soup.find("span", class_="minutes-date")
            date = date_element and date_element.text
            time_element = page_soup.find("div", class_="meeting-time")

            if time_element:
                time_match = self.time_pattern.search(time_element.text)
                if time_match:
                    time = time_match.group()

            # Find the link to the document
            document_link = page_soup.find("a", class_="document")
            if not document_link:
                self.logger.info(f"No agenda for {date}, continuing...")
                continue

            self.logger.info(f"Found agenda for {date}")

            download_url = base_url + document_link.get("href")
            break

        # Close the browser
        driver.quit()

        if not download_url:
            self.logger.info("Failed to find any meeting agendas")
            return None

        scraper_return = ScraperReturn(name, date, time, page_url, download_url)
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
    scraper = BanyuleScraper()
    scraper.scraper()
