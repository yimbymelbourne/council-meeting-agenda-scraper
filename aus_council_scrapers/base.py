import datetime
import json
import logging
import re
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

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
    `location`: The location of the meeting (e.g. Council Chambers).\n
    `cleaned_time`: The time of the meeting as a time object.\n
    `cleaned_date`: The date of the meeting as a date object.\n
    """

    name: Optional[str]
    date: str
    time: Optional[str]
    webpage_url: str
    download_url: str
    location: Optional[str] = None

    # Cached properties
    _cleaned_time: Optional[datetime.time] = None
    _cleaned_date: Optional[datetime.date] = None

    @property
    def cleaned_time(self) -> Optional[datetime.time]:
        try:
            if not self.time:
                return None
            if not self._cleaned_time:
                self._cleaned_time = parse_date(self.time, fuzzy=True).time()
            return self._cleaned_time
        except Exception as e:
            return None

    @property
    def cleaned_date(self) -> datetime.date:
        if not self.date:
            raise ValueError("Date is required")

        try:
            if not self._cleaned_date:
                self._cleaned_date = parse_date(self.date, fuzzy=True).date()
        except Exception as e:
            raise ValueError(f"Could not parse date {self.date}")

        return self._cleaned_date

    @property
    def cleaned_location(self) -> Optional[str]:
        if not self.location or self.location.isspace():
            return None

        cleaned = self.location.replace(r"\w", " ").strip().lower()

        # Remove council chambers string from location
        council_chamber_regex = re.compile(r"^council\s?chambers?,?", re.IGNORECASE)
        cleaned = council_chamber_regex.sub("", cleaned)

        if cleaned == "":
            return None

        return " ".join((word.capitalize() for word in cleaned.split()))

    def check_required_properties(self, state: str) -> None:
        if not self.name or self.name.isspace():
            raise ValueError(f"No name found")
        if not self.download_url or self.download_url.isspace():
            raise ValueError(f"No download URL found")
        if not self.webpage_url or self.webpage_url.isspace():
            raise ValueError(f"No webpage URL found")

        # cleaned date check happens in the property getter
        _ = self.cleaned_date

        # Check if date is in the past
        # TODO: Do we want to add this check to make sure we're not scraping meetings that happened in the past?
        # if self.is_date_in_past(state):
        #     raise ValueError(f"Meeting date is in the past")

    def add_default_values(self, default_name, default_time, default_location):
        if not self.name and default_name:
            self.name = default_name
        if not self.time and default_time:
            self.time = default_time
        if not self.cleaned_location and default_location:
            self.location = default_location

    def is_date_in_past(self, state: str) -> bool:
        timezone = pytz.timezone(TIMEZONES_BY_STATE[state.upper()])
        today = datetime.datetime.now(timezone).date()
        return self.cleaned_date < today

    def __str__(self):
        return json.dumps(self.to_dict(), indent=2)

    def to_dict(self):
        return {
            "name": self.name,
            "date": self.date,
            "time": self.time,
            "location": self.location,
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
            location=d.get("location"),
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
        self.keyword_regexes: list[re.Pattern] = COUNCIL_HOUSING_REGEX
        self.fetcher = DefaultFetcher()

        self.default_name: str = f"{self.council_name.capitalize()} Council Meeting"
        self.default_time: Optional[str] = None
        self.default_location: Optional[str] = None

    @abstractmethod
    def scraper(self) -> ScraperReturn | None:
        raise NotImplementedError("Scrape method must be implemented by the subclass.")


class InfoCouncilScraper(BaseScraper):
    def __init__(self, council, state, base_url, infocouncil_url):
        self.infocouncil_url = infocouncil_url
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn | None:

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

        date_text = current_meeting.find("td", class_="bpsGridDate").get_text(
            separator=" "
        )
        time_search = self.time_regex.search(date_text)
        time = time_search.group() if time_search else None

        date_search = self.date_regex.search(date_text)
        date = date_search.group() if date_search else None

        location = current_meeting.find("td", class_="bpsGridCommittee")
        location_text = None
        location_spans = [location_span for location_span in location.find_all("span")]
        for span_el in reversed(location_spans):
            maybe_address = span_el.get_text(separator=" ", strip=True)
            if maybe_address and maybe_address != "":
                location_text = maybe_address
                break

        name = location.text if location else None

        scraper_return = ScraperReturn(
            name=name,
            date=date,
            time=time,
            webpage_url=self.infocouncil_url,
            download_url=urllib.parse.urljoin(self.infocouncil_url, relative_pdf_url),
            location=location_text,
        )

        return scraper_return


SCRAPER_REGISTRY: dict[str, BaseScraper] = {}
