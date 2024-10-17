import datetime
import json
import logging
import re
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generator, Self, Optional

import pytz
import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

from aus_council_scrapers.constants import (
    COUNCIL_HOUSING_REGEX,
    DATE_REGEX,
    TIME_REGEX,
    TIMEZONES_BY_STATE,
)
from .data import ScraperResult, NoticeDate, NoticeLocation, NoticeHydrationInputs


def register_scraper(cls):
    SCRAPER_REGISTRY[cls.__name__] = cls()
    return cls


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
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"{self.__class__.__name__} initialized")

        self.council_name = council_name
        self.state = state
        self.base_url = base_url

        self.time_regex: re.Pattern = TIME_REGEX
        self.date_regex: re.Pattern = DATE_REGEX
        self.keyword_regexes: list[str] = COUNCIL_HOUSING_REGEX
        self.fetcher = DefaultFetcher()

        self.default_name: str = f"{self.council_name.capitalize()} Council Meeting"
        self.default_location: Optional[str] = None

    def hydration_options(self: Self) -> NoticeHydrationInputs:
        return NoticeHydrationInputs(self.default_name, self.default_location)

    @abstractmethod
    def scraper(self: Self) -> Generator[ScraperResult.Notice, None]:
        raise NotImplementedError("Scrape method must be implemented by the subclass.")


class InfoCouncilScraper(BaseScraper):
    def __init__(self, council, state, base_url, infocouncil_url):
        self.infocouncil_url = infocouncil_url
        super().__init__(council, state, base_url)

    def scraper(self: Self) -> Generator[ScraperResult.Notice, None]:
        output = self.fetcher.fetch_with_requests(self.infocouncil_url)
        soup = BeautifulSoup(output, "html.parser")
        meeting_table = soup.find("table", id="grdMenu", recursive=True)

        if meeting_table is None:
            self.logger.info(f"{self.council_name} scraper found no meetings")
            return

        current_meeting = meeting_table.find("tbody").find_all("tr")[0] # type: ignore

        relative_pdf_url = current_meeting.find(
            "a", class_="bpsGridPDFLink", recursive=True
        ).attrs["href"]

        date_text = current_meeting.find("td", class_="bpsGridDate").get_text(
            separator=" "
        )
        time_search = self.time_regex.search(date_text)
        time: str | None = time_search.group() if time_search else None

        date_search = self.date_regex.search(date_text)
        date: str | None = date_search.group() if date_search else None
        if date is None:
            return

        location = current_meeting.find("td", class_="bpsGridCommittee")
        location_text = None
        location_spans = [location_span for location_span in location.find_all("span")]
        for span_el in reversed(location_spans):
            maybe_address = span_el.get_text(separator=" ", strip=True)
            if maybe_address and maybe_address != "":
                location_text = maybe_address
                break

        name = location.text if location else None

        yield ScraperResult.CouncilMeetingNotice(
            name=name,
            datetime=NoticeDate.FuzzyRaw(raw_date=date, raw_time=time),
            webpage_url=self.infocouncil_url,
            download_url=urllib.parse.urljoin(self.infocouncil_url, relative_pdf_url),
            location=NoticeLocation.Raw(location_text),
        )


SCRAPER_REGISTRY: dict[str, BaseScraper] = {}
