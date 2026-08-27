import datetime
import json
import logging
import os
import random
import re
import time
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

from aus_council_scrapers import clock
from aus_council_scrapers.constants import (
    COUNCIL_HOUSING_REGEX,
    DATE_REGEX,
    EARLIEST_YEAR,
    TIME_REGEX,
    TIMEZONES_BY_STATE,
)


USER_AGENT_ISSUE = (
    "https://github.com/yimbymelbourne/council-meeting-agenda-scraper/issues/142"
)


class BlockedByWAF(requests.HTTPError):
    """A council's firewall rejected us with 403.

    This is a known, tracked problem with a known cause, so it should stop
    work on that council rather than prompt a workaround.
    """

    def __init__(self, url: str):
        super().__init__(
            f"403 for {url}\n\n"
            f"This council's firewall is blocking us. Do NOT work around it — "
            f"it is a known issue with a pending decision, tracked at:\n"
            f"  {USER_AGENT_ISSUE}\n\n"
            f"The cause is our spoofed browser User-Agent: 13 of 15 blocked "
            f"councils return 200 with an identifying User-Agent instead. "
            f"Defer this council until that issue is resolved.\n\n"
            f"(cardinia stays blocked either way, behind a Cloudflare "
            f"challenge — that one needs Selenium, not a header.)"
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
    `agenda_url`: The URL of the agenda PDF (optional).\n
    `minutes_url`: The URL of the minutes PDF (optional).\n
    `agenda_html_url`: The URL of the agenda in HTML format (optional).\n
    `minutes_html_url`: The URL of the minutes in HTML format (optional).\n
    `download_url`: [DEPRECATED] The URL of the PDF - use agenda_url/minutes_url instead.\n
    `location`: The location of the meeting (e.g. Council Chambers).\n
    `cleaned_time`: The time of the meeting as a time object.\n
    `cleaned_date`: The date of the meeting as a date object.\n
    """

    name: Optional[str]
    date: str
    time: Optional[str]
    webpage_url: str
    download_url: str = None  # Deprecated - kept for backward compatibility
    agenda_url: Optional[str] = None
    minutes_url: Optional[str] = None
    agenda_html_url: Optional[str] = None
    minutes_html_url: Optional[str] = None
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

        # At least one of agenda_url, minutes_url, or download_url must be present
        has_agenda = self.agenda_url and not self.agenda_url.isspace()
        has_minutes = self.minutes_url and not self.minutes_url.isspace()
        has_download = self.download_url and not self.download_url.isspace()

        if not (has_agenda or has_minutes or has_download):
            raise ValueError(
                f"No document URLs found (agenda_url, minutes_url, or download_url required)"
            )

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

    def __eq__(self, other):
        """Strict field-by-field equality.

        This deliberately has no backward-compatibility branches. Earlier
        versions treated a missing ``minutes_url`` on either side as a match
        and let a one-meeting fixture satisfy a many-meeting result, which
        meant a scraper could regress from hundreds of meetings to one and
        still pass. Cassettes recorded in the old shape are normalised on the
        way in by ``from_dict`` instead.
        """
        if not isinstance(other, ScraperReturn):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def to_dict(self):
        return {
            "name": self.name,
            "date": self.date,
            "time": self.time,
            "location": self.location,
            "webpage_url": self.webpage_url,
            "download_url": self.download_url,  # Kept for backward compatibility
            "agenda_url": self.agenda_url,
            "minutes_url": self.minutes_url,
            "agenda_html_url": self.agenda_html_url,
            "minutes_html_url": self.minutes_html_url,
        }

    @staticmethod
    def from_dict(d):
        """Load exactly what is in the record — no inference.

        This used to copy ``download_url`` into ``agenda_url`` when the latter
        was absent. That invented documents: for a minutes-only meeting whose
        ``download_url`` points at the minutes, it manufactured an agenda that
        does not exist, and it made recorded fixtures compare unequal to the
        very scraper output they were recorded from.
        """
        return ScraperReturn(
            name=d["name"],
            date=d["date"],
            time=d["time"],
            webpage_url=d["webpage_url"],
            download_url=d.get("download_url"),
            agenda_url=d.get("agenda_url"),
            minutes_url=d.get("minutes_url"),
            agenda_html_url=d.get("agenda_html_url"),
            minutes_html_url=d.get("minutes_html_url"),
            location=d.get("location"),
        )


class Fetcher(ABC):
    @abstractmethod
    def get_selenium_driver(self):
        raise NotImplementedError()

    @abstractmethod
    def fetch_with_requests(self, url, method="GET", **kwargs) -> str:
        raise NotImplementedError()

    @abstractmethod
    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise NotImplementedError()

    def sleep(self, seconds: float) -> None:
        """Wait for a page to settle after driving it.

        Scrapers should call this rather than ``time.sleep`` directly: during
        replay nothing is actually loading, so the playback fetcher overrides
        it to return immediately.
        """
        time.sleep(seconds)

    def close(self) -> None:
        pass


class DefaultFetcher(Fetcher):
    """Live fetcher, throttled per host.

    Councils sit behind WAFs that block on request *rate* far more often than
    on anything about the client itself, and a re-record of one InfoCouncil
    site is eight year-pages back to back. Requests to the same host are
    spaced by `FETCH_DELAY` seconds (jittered, so the pattern is not a
    metronome), and 429/403/503 responses are retried with exponential
    backoff honouring `Retry-After`.

    The delay is keyed by host, so scraping different councils concurrently
    is unaffected.
    """

    DEFAULT_FETCH_DELAY = 2.0
    MAX_RETRIES = 4
    RETRY_STATUSES = frozenset({403, 429, 500, 502, 503, 504})

    def __init__(self, fetch_delay: Optional[float] = None):
        self.__session = requests.Session()
        self.__set_headers(self.DEFAULTHEADERS)
        self.__driver = None
        self.__last_request_at: dict[str, float] = {}
        self.__logger = logging.getLogger(self.__class__.__name__)

        if fetch_delay is None:
            fetch_delay = float(
                os.environ.get("FETCH_DELAY", self.DEFAULT_FETCH_DELAY)
            )
        self.__fetch_delay = fetch_delay

    def __throttle(self, url: str) -> None:
        """Space out consecutive requests to the same host."""
        if self.__fetch_delay <= 0:
            return

        host = urllib.parse.urlparse(url).netloc
        last = self.__last_request_at.get(host)
        if last is not None:
            # Jitter so a long run of requests is not perfectly periodic.
            wait = self.__fetch_delay * random.uniform(0.75, 1.25) - (
                time.monotonic() - last
            )
            if wait > 0:
                time.sleep(wait)
        self.__last_request_at[host] = time.monotonic()

    def __backoff(self, response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After") if response else None
        if retry_after:
            try:
                return min(float(retry_after), 120.0)
            except ValueError:
                pass
        return min(self.__fetch_delay * (2**attempt), 60.0)

    DEFAULTHEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.62 Safari/537.3",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        # application/javascript is needed by councils whose meeting list is a
        # single-page app: fetching its script bundle is the only way to read the
        # settings it uses to build document URLs. Servers that negotiate
        # strictly answer 406 when the type is missing.
        "Accept": (
            "application/json, text/html, application/xml, text/plain,"
            " application/javascript"
        ),
    }

    def __set_headers(self, headers):
        # Directly replace the session's headers dictionary
        self.__session.headers.clear()
        self.__session.headers.update(headers)

    def __setup_selenium_driver(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        # Suppress automation signals that bot-detection (e.g. Akamai) checks for
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        self.__driver = webdriver.Chrome(options=chrome_options)
        self.__driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            },
        )

    def get_selenium_driver(self):
        if not self.__driver:
            self.__setup_selenium_driver()
        return self.__driver

    def fetch_with_requests(self, url, method="GET", **kwargs):
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            self.__throttle(url)
            try:
                if method.upper() == "POST":
                    response = self.__session.post(url, **kwargs)
                else:
                    response = self.__session.get(url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as e:
                # A dropped connection is exactly the transient failure this
                # fetcher exists to absorb (see class docstring) -- confirmed
                # against a real one, ~600 requests into a long recording,
                # not a hypothetical. Retry it the same as a retryable status
                # code rather than aborting the whole scrape on one flaky
                # request.
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.__backoff(None, attempt)
                    self.__logger.warning(
                        f"{e.__class__.__name__} from {url} — backing off "
                        f"{delay:.1f}s (attempt {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    time.sleep(delay)
                    continue
                raise
            else:
                if response.status_code not in self.RETRY_STATUSES:
                    response.raise_for_status()
                    return response.text

                last_error = requests.HTTPError(
                    f"{response.status_code} for {url}", response=response
                )
                if response.status_code == 403:
                    # Not a transient failure and not something to engineer
                    # around. A measured 13 of 15 blocked councils return 200
                    # as soon as we send an identifying User-Agent instead of
                    # the spoofed browser one, so a workaround here would be
                    # solving the wrong problem.
                    last_error = BlockedByWAF(url)
                    break
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.__backoff(response, attempt)
                    self.__logger.warning(
                        f"{response.status_code} from {url} — backing off {delay:.1f}s "
                        f"(attempt {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    time.sleep(delay)

        raise last_error

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        if not self.__driver:
            self.__setup_selenium_driver()
        self.__throttle(url)
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
    def scraper(self) -> list[ScraperReturn]:
        raise NotImplementedError("Scrape method must be implemented by the subclass.")


_DOCUMENT_FIELDS = ("agenda_url", "minutes_url", "agenda_html_url", "minutes_html_url")


def _merge_split_meetings(results: list[ScraperReturn]) -> list[ScraperReturn]:
    """Combine rows that are one meeting split across separate listings.

    Some InfoCouncil sites emit two `div.meeting-row` entries for a single
    meeting — one carrying the agenda, another the minutes. Left alone that
    produces two records for one meeting, each missing half its documents,
    which defeats the point of holding agenda and minutes together.

    Only complementary rows are merged. Two rows sharing a name and date but
    each holding a *different* agenda are two real meetings — a council can
    hold two special meetings on one night — so any conflicting field blocks
    the merge and both records survive.
    """
    merged: list[ScraperReturn] = []
    by_identity: dict[tuple, ScraperReturn] = {}

    for record in results:
        key = (record.name, record.date)
        existing = by_identity.get(key)

        if existing is None or any(
            getattr(existing, field)
            and getattr(record, field)
            and getattr(existing, field) != getattr(record, field)
            for field in _DOCUMENT_FIELDS
        ):
            by_identity.setdefault(key, record)
            merged.append(record)
            continue

        for field in _DOCUMENT_FIELDS:
            if not getattr(existing, field):
                setattr(existing, field, getattr(record, field))
        for field in ("time", "location"):
            if not getattr(existing, field):
                setattr(existing, field, getattr(record, field))
        # download_url is deprecated but still consumed: keep it pointing at
        # the agenda now that one is known.
        if not existing.download_url:
            existing.download_url = existing.agenda_url or existing.minutes_url

    return merged


class InfoCouncilScraper(BaseScraper):
    def __init__(self, council, state, base_url, infocouncil_url):
        self.infocouncil_url = infocouncil_url
        super().__init__(council, state, base_url)

    def scraper(self) -> list[ScraperReturn]:
        """
        Scrape InfoCouncil meeting data.
        Attempts to fetch meetings from multiple years by trying year query parameters.
        """
        results = []

        # Try from EARLIEST_YEAR to current year + 2 (meetings published up to 2 years in advance)
        # InfoCouncil sites may support ?year=YYYY parameter
        current_year = clock.current_year()
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            years_to_try = sorted(years_filter)
        else:
            years_to_try = range(EARLIEST_YEAR, current_year + 3)

        for year in years_to_try:
            year_url = f"{self.infocouncil_url}?year={year}"
            try:
                output = self.fetcher.fetch_with_requests(year_url)
                soup = BeautifulSoup(output, "html.parser")
                meeting_table = soup.find("table", id="grdMenu", recursive=True)

                if meeting_table is None:
                    # InfoCouncil is rolling out a redesigned template that drops
                    # table#grdMenu for a div layout. Fall back to that before
                    # giving up on the year.
                    results.extend(self._scrape_responsive_rows(soup, year))
                    continue

                # Get all meeting rows
                meeting_rows = meeting_table.find("tbody").find_all("tr")

                # Process each meeting row
                for current_meeting in meeting_rows:
                    # Look for agenda PDF link.
                    #
                    # Search inside the agenda cell, not the whole row. Minutes
                    # links carry the same bpsGridPDFLink class, so searching
                    # the row meant a meeting with minutes but no agenda stored
                    # its minutes PDF as the agenda — inventing an agenda that
                    # does not exist. That affected 76 meetings across ten
                    # councils.
                    agenda_cell = current_meeting.find("td", class_="bpsGridAgenda")
                    agenda_link = (
                        agenda_cell.find("a", class_="bpsGridPDFLink")
                        if agenda_cell
                        else None
                    )
                    agenda_url = None
                    if agenda_link and "href" in agenda_link.attrs:
                        agenda_url = urllib.parse.urljoin(
                            self.infocouncil_url, agenda_link["href"]
                        )

                    # Look for agenda HTML link
                    agenda_html_url = None
                    agenda_html_link = None
                    if agenda_cell:
                        agenda_html_link = agenda_cell.find(
                            "a", class_="bpsGridHTMLLink"
                        )
                    if agenda_html_link and "href" in agenda_html_link.attrs:
                        agenda_html_url = urllib.parse.urljoin(
                            self.infocouncil_url, agenda_html_link["href"]
                        )

                    # Look for minutes PDF link - often has a different class or text
                    minutes_url = None
                    minutes_link = current_meeting.find(
                        "a", class_="bpsGridMinutesLink", recursive=True
                    )
                    if not minutes_link:
                        # Try finding in the minutes column specifically
                        minutes_cell = current_meeting.find(
                            "td", class_="bpsGridMinutes"
                        )
                        if minutes_cell:
                            # Look for PDF link first
                            pdf_link = minutes_cell.find("a", class_="bpsGridPDFLink")
                            if pdf_link and "href" in pdf_link.attrs:
                                minutes_link = pdf_link
                            else:
                                # Fall back to any link with "minutes" in the text
                                for link in minutes_cell.find_all("a"):
                                    if (
                                        "minutes" in link.get_text().lower()
                                        and "href" in link.attrs
                                    ):
                                        minutes_link = link
                                        break

                    if minutes_link and "href" in minutes_link.attrs:
                        minutes_url = urllib.parse.urljoin(
                            self.infocouncil_url, minutes_link["href"]
                        )

                    # Look for minutes HTML link
                    minutes_html_url = None
                    minutes_cell = current_meeting.find("td", class_="bpsGridMinutes")
                    if minutes_cell:
                        minutes_html_link = minutes_cell.find(
                            "a", class_="bpsGridHTMLLink"
                        )
                        if minutes_html_link and "href" in minutes_html_link.attrs:
                            minutes_html_url = urllib.parse.urljoin(
                                self.infocouncil_url, minutes_html_link["href"]
                            )

                    date_text = current_meeting.find(
                        "td", class_="bpsGridDate"
                    ).get_text(separator=" ")
                    time_search = self.time_regex.search(date_text)
                    time = time_search.group() if time_search else None

                    date_search = self.date_regex.search(date_text)
                    date = date_search.group() if date_search else None

                    # Skip rows where the date doesn't belong to the queried year.
                    # Some sites ignore ?year= and always return the current year's
                    # data, which would otherwise cause duplicates across year queries.
                    if date:
                        try:
                            if parse_date(date, fuzzy=True).year != year:
                                continue
                        except Exception:
                            pass

                    location = current_meeting.find("td", class_="bpsGridCommittee")
                    location_text = None
                    location_spans = [
                        location_span for location_span in location.find_all("span")
                    ]
                    for span_el in reversed(location_spans):
                        maybe_address = span_el.get_text(separator=" ", strip=True)
                        if maybe_address and maybe_address != "":
                            location_text = maybe_address
                            break

                    name = location.text if location else None

                    if not agenda_url and not minutes_url:
                        continue

                    scraper_return = ScraperReturn(
                        name=name,
                        date=date,
                        time=time,
                        webpage_url=self.infocouncil_url,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        agenda_html_url=agenda_html_url,
                        minutes_html_url=minutes_html_url,
                        download_url=agenda_url,  # For backward compatibility
                        location=location_text,
                    )
                    results.append(scraper_return)

            except Exception as e:
                # Log but continue trying other years
                self.logger.debug(f"Failed to fetch meetings for year {year}: {e}")
                continue

        # The legacy grid splits some meetings across two rows in the same way
        # the redesigned template does — one carrying the agenda, another the
        # minutes. That was invisible until agenda links stopped being read
        # from the whole row, because the minutes row was given a fabricated
        # agenda and so never looked like half a meeting.
        results = _merge_split_meetings(results)

        if not results:
            self.logger.info(f"{self.council_name} scraper found no meetings")
        else:
            self.logger.info(
                f"{self.council_name} scraper found {len(results)} meetings"
            )

        return results

    def _scrape_responsive_rows(self, soup, year: int) -> list[ScraperReturn]:
        """Parse the redesigned InfoCouncil template.

        Instead of table#grdMenu, each meeting is a `div.meeting-row` holding
        `.meeting-date`, `.meeting-time`, `.meeting-title` and `.meeting-location`,
        with documents grouped under `.paper-group-header` labels ("Agenda",
        "Minutes", "Agenda - Supplementary", ...). Unlike the legacy grid, this
        template exposes the meeting time and location directly.
        """
        results = []

        for row in soup.find_all("div", class_="meeting-row"):
            date_text = self._responsive_text(row, "meeting-date")
            time_text = self._responsive_text(row, "meeting-time")

            date_search = self.date_regex.search(date_text) if date_text else None
            date = date_search.group() if date_search else None

            # Some sites ignore ?year= and always return the latest listing,
            # which would otherwise duplicate meetings across year queries.
            if date:
                try:
                    if parse_date(date, fuzzy=True).year != year:
                        continue
                except Exception:
                    pass

            time_search = self.time_regex.search(f"{date_text} {time_text}".strip())
            time = time_search.group() if time_search else None

            papers = self._responsive_papers(row)
            agenda_url = papers.get("agenda_pdf")
            minutes_url = papers.get("minutes_pdf")

            if not agenda_url and not minutes_url:
                continue

            results.append(
                ScraperReturn(
                    name=self._responsive_text(row, "meeting-title") or None,
                    date=date,
                    time=time,
                    webpage_url=self.infocouncil_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    agenda_html_url=papers.get("agenda_html"),
                    minutes_html_url=papers.get("minutes_html"),
                    download_url=agenda_url,  # For backward compatibility
                    location=self._responsive_text(row, "meeting-location") or None,
                )
            )

        return _merge_split_meetings(results)

    @staticmethod
    def _responsive_text(row, class_name: str) -> str:
        element = row.find(class_=class_name)
        return element.get_text(" ", strip=True) if element else ""

    def _responsive_papers(self, row) -> dict:
        """Map the paper groups in a `div.meeting-row` to document URLs.

        A meeting can carry several agenda or minutes groups - a supplementary
        agenda, an extraordinary one - so the plainly labelled "Agenda" and
        "Minutes" groups are read first and win over the variants.
        """
        papers = {}

        for exact_labels_only in (True, False):
            for header in row.find_all(class_="paper-group-header"):
                label = header.get_text(" ", strip=True).lower()
                if (label in ("agenda", "minutes")) != exact_labels_only:
                    continue

                if label.startswith("agenda"):
                    kind = "agenda"
                elif label.startswith("minutes"):
                    kind = "minutes"
                else:
                    continue

                items = header.find_next_sibling(class_="paper-items")
                if items is None:
                    continue

                for link in items.find_all("a", class_="paper-link", href=True):
                    url = urllib.parse.urljoin(self.infocouncil_url, link["href"])
                    suffix = "pdf" if url.lower().endswith(".pdf") else "html"
                    papers.setdefault(f"{kind}_{suffix}", url)

        return papers


SCRAPER_REGISTRY: dict[str, BaseScraper] = {}
