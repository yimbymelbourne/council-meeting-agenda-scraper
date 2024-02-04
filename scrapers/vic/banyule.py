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
        super().__init__( council, state, base_url)
        self.time_pattern = re.compile(r"\d+:\d+\s?[apmAPM]+")

    def scraper(self) -> ScraperReturn | None:
        return None

        """
        Needs a bit of refinement, doesn't seem to work in headless mode, and inconsistent in display mode
        """
        # base_url = "https://www.banyule.vic.gov.au"
        # webpage_url = "https://www.banyule.vic.gov.au/About-us/Councillors-and-Council-meetings/Council-meetings/Council-meeting-agendas-and-minutes"

        # chrome_options = Options()
        # chrome_options.add_argument("--headless")
        # driver = webdriver.Chrome(options=chrome_options)

        # name = None
        # date = None
        # time = None
        # download_url = None

        # driver.get(webpage_url)

        # # Reload the page, as the first time we visit javascript does not get loaded
        # # for some reason
        # driver.refresh()

        # # Open all the accordions
        # WebDriverWait(driver, 5)
        # driver.execute_script("Array.from(document.getElementsByClassName('accordion-trigger')).forEach(e => e.click())")
        # WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".accordion-list-item-container .initialised")))
        # wait = WebDriverWait(driver, 5)
        # wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".accordion-list-item-container .initialised")))

        # # Give a little time for all accordions to load, just in case. may not be necessary
        # driver.implicitly_wait(10)

        # # Get the HTML
        # output = driver.page_source
        # driver.quit()

        # # Feed the HTML to BeautifulSoup
        # initial_soup = BeautifulSoup(output, "html.parser")

        # sections = initial_soup.find_all("div", class_="accordion-list-item-container")

        # for section in sections:
        #     document_link = section.find("a", class_="document")
        #     if not document_link:
        #         continue

        #     name_element = section.find("span", class_="meeting-type")
        #     name = name_element and name_element.text
        #     date_element = section.find("span", class_="minutes-date")
        #     date = date_element and date_element.text
        #     time_element = section.find("div", class_="meeting-time")

        #     if time_element:
        #         time_match = self.time_pattern.search(time_element.text)
        #         if time_match:
        #             time = time_match.group()

        #     download_url = base_url + document_link.get("href")
        #     break

        # if not download_url:
        #     print("Failed to find any meeting agendas")
        #     return None

        # print("~~~")
        # scraper_return = ScraperReturn(name, date, time, base_url, download_url)

        # print(
        #     scraper_return.name,
        #     scraper_return.date,
        #     scraper_return.time,
        #     scraper_return.webpage_url,
        #     scraper_return.download_url,
        # )

        # return scraper_return



if __name__ == "__main__":
    scraper = BanyuleScraper()
    scraper.scraper()