# base_scraper.py
import logging
import requests
from abc import ABC, abstractmethod
from council_scrapers.constants import COUNCIL_HOUSING_REGEX, TIME_REGEX, DATE_REGEX
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from dataclasses import dataclass
import urllib.parse
from bs4 import BeautifulSoup
import re

from typing import Callable, List, Optional, TypedDict


def register_scraper(cls):
    SCRAPER_REGISTRY[cls.__name__] = cls()
    return cls


@dataclass
class ScraperReturn:
    """Designates what a scraper should return.\n
    If a given item in the scraper is None, it will be skipped.\n
    `name`: The name of the meeting (e.g. City Development Delegated Committee).\n
    `date`: The date of the meeting (e.g. 2021-08-01).\n
    `time`: The time of the meeting (e.g. 18:00).\n
    `webpage_url`: The URL of the webpage where the agenda is found.\n
    `download_url`: The URL of the PDF of the agenda.\n
    """

    name: str
    date: str
    time: str
    webpage_url: str
    download_url: str

    def to_dict(self):
        return {
            "name": self.name,
            "date": self.date,
            "time": self.time,
            "webpage_url": self.webpage_url,
            "download_url": self.download_url,
        }

    @staticmethod
    def from_dict(d):
        return ScraperReturn(
            name=d["name"],
            date=d["date"],
            time=d["time"],
            webpage_url=d["webpage_url"],
            download_url=d["download_url"],
        )


class Fetcher(ABC):
    @abstractmethod
    def get_selenium_driver(self):
        raise NotImplementedError()

    @abstractmethod
    def fetch_with_requests(self, url, method="GET") -> str:
        raise NotImplementedError()

    @abstractmethod
    def fetch_with_selenium(self, url):
        raise NotImplementedError()

    def close(self) -> None:
        pass


class DefaultFetcher(Fetcher):
    def __init__(self):
        self.__session = requests.Session()
        self.__set_headers(self.DEFAULTHEADERS)
        self.__driver = None

    DEFAULTHEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.62 Safari/537.3",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        "Accept": "application/json, text/html, application/xml, text/plain",
    }

    def __set_headers(self, headers):
        # Directly replace the session's headers dictionary
        self.__session.headers.clear()
        self.__session.headers.update(headers)

    def __setup_selenium_driver(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        self.__driver = webdriver.Chrome(options=chrome_options)

    def get_selenium_driver(self):
        if not self.__driver:
            self.__setup_selenium_driver()
        return self.__driver

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if method.upper() == "POST":
            response = self.__session.post(url, **kwargs)
        else:
            response = self.__session.get(url, **kwargs)
        response.raise_for_status()
        return response.text

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        if not self.__driver:
            self.__setup_selenium_driver()
        self.__driver.get(url)
        if wait_condition:
            WebDriverWait(self.__driver, wait_time).until(wait_condition)
        return self.__driver.page_source

    def close(self) -> None:
        if self.__driver:
            self.__driver.quit()


class BaseScraper(ABC):
    """
    Base class for all council scrapers.

    Attributes:
        `DEFAULTHEADERS (dict)`: Default headers for the requests.
        `council_name (str)`: Name of the council to scrape (snake_case).
        `state (str)`: State of the council.
        `base_url (str)`: Base URL for the council's website.
        `logger (logging.Logger)`: Logger instance for the scraper.
        `session (requests.Session)`: Session object for making requests.
        `driver (selenium.webdriver.Chrome)`: Selenium WebDriver instance.
        `time_regex (re.Pattern)`: Regular expression for matching times. Overwrite in subclass if necessary.
        `date_regex (re.Pattern)`: Regular expression for matching dates. Overwrite in subclass if necessary.

    Methods:
        `log(level, message, *args)`: Logs a message with the provided level, including council name and state.
        `fetcher.set_headers(headers)`: Sets the headers for the session.
        `fetcher.setup_selenium_driver()`: Sets up a Selenium WebDriver instance.
        `fetcher.get_selenium_driver()`: Returns the Selenium WebDriver instance, setting it up if necessary.
        `fetcher.fetch_with_requests(url, method="GET", **kwargs)`: Fetches a URL with the requests module.
        `fetcher.fetch_with_selenium(url, wait_time=10, wait_condition=None)`: Fetches a URL with Selenium, optionally waiting for a condition.
        `scraper()`: Abstract method for scraping the council's website. Must be implemented by subclasses.
        `close()`: Closes the Selenium WebDriver instance if it exists.
    """

    def __init__(
        self,
        council_name: str,
        state: str,
        base_url: str,
    ):
        self.council_name = council_name
        self.state = state
        self.base_url = base_url
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"{self.__class__.__name__} initialized")
        self.time_regex: re.Pattern = TIME_REGEX
        self.date_regex: re.Pattern = DATE_REGEX
        self.keyword_regexes: list[re.Pattern] = COUNCIL_HOUSING_REGEX
        self.fetcher = DefaultFetcher()

    def log(self, level, message, *args):
        # Prepare a message that includes council name and state
        full_message = f"[{self.council_name} - {self.state}] {message}"
        # Get the logger with the name of the current class
        logger = logging.getLogger(self.__class__.__name__)
        # Log the message with the provided level
        logger.log(level, full_message, *args)

    @abstractmethod
    def scraper(self) -> ScraperReturn | None:
        raise NotImplementedError("Scrape method must be implemented by the subclass.")


class InfoCouncilScraper(BaseScraper):
    def __init__(self, council, state, base_url, infocouncil_url):
        self.infocouncil_url = infocouncil_url
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn | None:
        self.logger.info(f"Starting {self.council_name} scraper")
        output = self.fetcher.fetch_with_requests(self.infocouncil_url)
        soup = BeautifulSoup(output, "html.parser")
        meeting_table = soup.find("table", id="grdMenu", recursive=True)
        if meeting_table is None:
            self.logger.info(f"{self.council_name} scraper found no meetings")
            scraper_return = ScraperReturn(
                name=None, date=None, time=None, webpage_url=None, download_url=None
            )
            return scraper_return
        current_meeting = meeting_table.find("tbody").find_all("tr")[0]

        relative_pdf_url = current_meeting.find(
            "a", class_="bpsGridPDFLink", recursive=True
        ).attrs["href"]
        date_element = current_meeting.find("td", class_="bpsGridDate")
        if date_element.span is not None:
            time = date_element.span.text
        else:
            time = ""
        scraper_return = ScraperReturn(
            name=current_meeting.find("td", class_="bpsGridCommittee").text,
            date=date_element.contents[0],
            time=time,
            webpage_url=self.infocouncil_url,
            download_url=urllib.parse.urljoin(self.infocouncil_url, relative_pdf_url),
        )

        self.logger.info(f"{self.council_name} scraper finished successfully")
        return scraper_return


SCRAPER_REGISTRY: dict[str, BaseScraper] = {}
