import datetime
import json
import logging
import os
import random
import re
import signal
import socket
import subprocess
import threading
import time
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from xml.etree import ElementTree

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

# How we describe ourselves, one string per channel. Both are honest, which is
# the point: #142 objected to claiming to be a browser while not being one.
#
# On the requests channel we are a script, so we say so. We fetch agendas and
# minutes councils are legally required to publish, and an identifiable client
# with a contact URL can be allowlisted or contacted instead of silently
# blocked.
IDENTIFYING_USER_AGENT = (
    "aus-council-scrapers/0.1 "
    "(+https://github.com/yimbymelbourne/council-meeting-agenda-scraper)"
)

# A minority of councils run WAF rules that do the opposite: they reject
# anything that is not browser-shaped. Those get this string via a per-scraper
# `user_agent` override — never globally, or the 13 councils that only answer
# an identifying client go dark again.
#
# The trailing token is `Safari/537.36`. The string this replaced ended
# `537.3`, one digit short, which made it a rare fingerprint rather than a
# common one — the worst of both worlds.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def resolve_user_agent(override: Optional[str] = None) -> str:
    """The User-Agent for the requests channel.

    Precedence: an explicit per-scraper override, then the `USER_AGENT`
    environment variable, then the identifying default. The override wins over
    the environment on purpose — a scraper sets it because its council demands
    it, so an env var meant for everything else must not switch it off.
    """
    return override or os.environ.get("USER_AGENT") or IDENTIFYING_USER_AGENT


class BlockedByWAF(requests.HTTPError):
    """A council's firewall rejected us with 403.

    Since #142 was settled this means something narrower than it used to:
    we identified ourselves honestly and were refused anyway.
    """

    def __init__(self, url: str, user_agent: str):
        browser_hint = (
            f"You are already sending {BROWSER_USER_AGENT!r}, so this is not a "
            f"User-Agent problem. Check for a JS challenge "
            f"(`cf-mitigated`, `x-amzn-waf-action`), which needs Selenium."
            if user_agent == BROWSER_USER_AGENT
            else f"A few councils reject any client that is not browser-shaped "
            f"— `manningham` is one. If this is another, set\n"
            f"  user_agent = BROWSER_USER_AGENT\n"
            f"on the scraper class, and verify it against that council only.\n\n"
            f"Do NOT change the project-wide default: 13 councils are "
            f"reachable *because* it identifies us. Background: "
            f"{USER_AGENT_ISSUE}"
        )
        super().__init__(f"403 for {url}\n\nSent as: {user_agent}\n\n{browser_hint}")


# Residential egress: a few councils refuse GitHub's runners however we
# identify ourselves (see AGENTS.md, "Councils that block GitHub's runners").
# A scraper opts in with `egress = "residential"`, and its requests then go
# through the proxy named here. council-alerts sets it each night to a
# tinyproxy on a home machine, reached over Tailscale.
#
# Deliberately not HTTP(S)_PROXY: requests applies those to every session in
# the process, which would send every council through one home connection.
RESIDENTIAL_PROXY_ENV = "RESIDENTIAL_PROXY_URL"

# The value that means "this machine already has a residential IP": recording
# a cassette from home, or a local adapter run. Requests go direct.
RESIDENTIAL_PROXY_DIRECT = "direct"

EGRESS_MODES = ("direct", "residential")


class EgressUnavailable(Exception):
    """A residential-egress council was asked for with no way to reach it.

    Raised on the first fetch, not at construction, because every scraper is
    built at import time. It is an ordinary exception on purpose, so
    `run_scraper` reports it as `ok: false` with this type name and the
    council's stored meetings are left alone. The alternative—fetching
    direct and being refused—used to come back as an ok council with 0
    meetings.
    """

    def __init__(self, council: Optional[str], reason: str):
        self.council = council
        who = council or "this scraper"
        super().__init__(
            f"{who} needs residential egress, but {reason}. Set "
            f"{RESIDENTIAL_PROXY_ENV} to the proxy URL, or to "
            f"'{RESIDENTIAL_PROXY_DIRECT}' on a machine with a residential IP."
        )


# One TCP check per proxy per process, shared by every fetcher. main.py runs
# scrapers on worker threads, so the cache is guarded; the check itself runs
# under the lock too, which only ever holds up other residential councils
# waiting on the same answer.
_PROXY_PREFLIGHT_TIMEOUT_S = 5.0
_proxy_preflight_lock = threading.Lock()
_proxy_preflight_results: dict[str, Optional[str]] = {}


def _preflight_proxy(proxy_url: str) -> Optional[str]:
    """Return None if the proxy accepts a TCP connection, else why not.

    Without this a sleeping home machine costs each residential council a
    10 s connect timeout and surfaces as a bare `ConnectTimeout`. With it the
    failure is one short wait and a named `EgressUnavailable`.
    """
    with _proxy_preflight_lock:
        if proxy_url in _proxy_preflight_results:
            return _proxy_preflight_results[proxy_url]
        parsed = urllib.parse.urlparse(proxy_url)
        try:
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if not host:
                raise ValueError("no host in the URL")
            socket.create_connection((host, port), _PROXY_PREFLIGHT_TIMEOUT_S).close()
            problem = None
        except (OSError, ValueError) as e:
            problem = (
                f"the proxy at {parsed.hostname}:{parsed.port} did not accept a "
                f"connection ({type(e).__name__}: {e})"
            )
        _proxy_preflight_results[proxy_url] = problem
        return problem


def resolve_egress_proxy(egress: str, council: Optional[str] = None) -> Optional[str]:
    """The proxy URL for a fetcher's traffic, or None to go direct.

    Raises `EgressUnavailable` for a residential council when no proxy is
    configured or the configured one cannot be reached.
    """
    if egress == "direct":
        return None
    if egress != "residential":
        raise ValueError(f"unknown egress {egress!r}; expected one of {EGRESS_MODES}")

    proxy_url = os.environ.get(RESIDENTIAL_PROXY_ENV, "").strip()
    if not proxy_url:
        raise EgressUnavailable(council, f"{RESIDENTIAL_PROXY_ENV} is not set")
    if proxy_url == RESIDENTIAL_PROXY_DIRECT:
        return None
    problem = _preflight_proxy(proxy_url)
    if problem:
        raise EgressUnavailable(council, problem)
    return proxy_url


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

    def restart_driver(self) -> None:
        """Throw away the browser so the next fetch starts a fresh one.

        A scraper that loads dozens of heavy pages through one long-lived
        Chrome can find it dead mid-run — `InvalidSessionIdException`, "the
        browser has closed the connection" — after which every later fetch
        fails and the scraper looks merely unproductive. Retrying is useless
        against a dead session; restarting is not.

        A no-op by default so replay, which has no browser, ignores it.
        """
        return None

    def close(self) -> None:
        pass

    def abandon(self) -> None:
        """Kill any browser this fetcher started, without waiting on it.

        For a scraper the adapter is giving up on. `close` cannot be used:
        it asks the browser to quit over the same session that may be the
        thing that hung. A no-op by default, since only a live browser
        outlives the process.
        """
        return None


class DefaultFetcher(Fetcher):
    """Live fetcher, throttled per host.

    Councils sit behind WAFs that block on request *rate* far more often than
    on anything about the client itself, and a re-record of one InfoCouncil
    site is eight year-pages back to back. Requests to the same host are
    spaced by `FETCH_DELAY` seconds (jittered, so the pattern is not a
    metronome), and 429/403/503 responses are retried with exponential
    backoff honouring `Retry-After`.

    The spacing is per host *across the whole process*, not per fetcher.
    Every scraper builds its own fetcher, and many councils share one vendor
    host—a dozen Resolve tenants all call `api.resolve.red`, seven LGA SA
    councils call one Funnelback endpoint. A per-instance throttle let all of
    them hit that host at once, so `FETCH_DELAY` limited each council and
    nothing limited the vendor. Different hosts still run fully in parallel.

    Every request also carries a timeout. Without one a server that accepts
    the connection and then sends nothing blocks the worker forever:
    `api.docassembler.com.au` held a local run for 12+ minutes at 0% CPU, and
    in production that is the 600 s SIGKILL with nothing persisted for any
    council.
    """

    DEFAULT_FETCH_DELAY = 2.0
    MAX_RETRIES = 4
    RETRY_STATUSES = frozenset({403, 429, 500, 502, 503, 504})

    # (connect, read) seconds for requests. The read timeout bounds the gap
    # between bytes, not the whole download, so a big PDF listing that keeps
    # streaming is unaffected; only a silent server trips it. 60 s is far
    # above any response a council has taken to start answering. `FETCH_TIMEOUT`
    # overrides the read half from the council-alerts workflow without a PR
    # here. A total wall-clock bound is main.py's adapter budget, not this.
    CONNECT_TIMEOUT = 10.0
    DEFAULT_READ_TIMEOUT = 60.0

    # Selenium has no default page-load timeout at all—`driver.get` waits
    # for the load event indefinitely. Same reasoning, same order of magnitude.
    PAGE_LOAD_TIMEOUT = 60

    # Shared by every instance: the next free request slot per host. A
    # caller reserves a slot under the lock and sleeps *outside* it, so a
    # long wait on one host never blocks a request to another.
    _host_lock = threading.Lock()
    _next_slot_at: dict[str, float] = {}

    def __init__(
        self,
        fetch_delay: Optional[float] = None,
        user_agent: Optional[str] = None,
        strip_headless_user_agent: bool = False,
        egress: str = "direct",
        council: Optional[str] = None,
    ):
        self.__session = requests.Session()
        self.user_agent = resolve_user_agent(user_agent)
        self.strip_headless_user_agent = strip_headless_user_agent
        if egress not in EGRESS_MODES:
            raise ValueError(f"unknown egress {egress!r}; expected one of {EGRESS_MODES}")
        self.egress = egress
        # Only used to name the council in an EgressUnavailable message.
        self.council = council
        # Resolved on the first fetch, not here: scrapers are constructed at
        # import time, long before anyone has decided whether this run needs
        # the proxy, and a run that never touches this council must not fail
        # for lack of one.
        self.__egress_resolved = False
        self.__proxy_url: Optional[str] = None
        self.__set_headers({**self.DEFAULTHEADERS, "User-Agent": self.user_agent})
        self.__driver = None
        self.__logger = logging.getLogger(self.__class__.__name__)

        if fetch_delay is None:
            fetch_delay = float(
                os.environ.get("FETCH_DELAY", self.DEFAULT_FETCH_DELAY)
            )
        self.__fetch_delay = fetch_delay
        self.__timeout = (
            self.CONNECT_TIMEOUT,
            float(os.environ.get("FETCH_TIMEOUT", self.DEFAULT_READ_TIMEOUT)),
        )

    def __throttle(self, url: str) -> None:
        """Space out consecutive requests to the same host, process-wide."""
        if self.__fetch_delay <= 0:
            return

        host = urllib.parse.urlparse(url).netloc
        with DefaultFetcher._host_lock:
            now = time.monotonic()
            slot = max(now, DefaultFetcher._next_slot_at.get(host, now))
            # Jitter so a long run of requests is not perfectly periodic.
            DefaultFetcher._next_slot_at[host] = slot + (
                self.__fetch_delay * random.uniform(0.75, 1.25)
            )
        if slot > now:
            time.sleep(slot - now)

    def __backoff(self, response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After") if response else None
        if retry_after:
            try:
                return min(float(retry_after), 120.0)
            except ValueError:
                pass
        return min(self.__fetch_delay * (2**attempt), 60.0)

    DEFAULTHEADERS = {
        # Overridden per instance by `resolve_user_agent`; the value here is
        # what a caller reading DEFAULTHEADERS directly should send.
        "User-Agent": IDENTIFYING_USER_AGENT,
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

    def __ensure_egress(self) -> Optional[str]:
        """Route this fetcher through the residential proxy if it needs one.

        Runs before every fetch and does work only the first time. A failure
        is not cached on the instance, so it raises again on every later
        fetch too—a scraper that swallows one fetch error cannot then carry
        on direct and come back with a quiet 0 meetings.
        """
        if not self.__egress_resolved:
            self.__proxy_url = resolve_egress_proxy(self.egress, self.council)
            if self.__proxy_url:
                # Both schemes: an http:// link on a residential council's
                # site is as blocked as the https:// ones.
                self.__session.proxies.update(
                    {"http": self.__proxy_url, "https": self.__proxy_url}
                )
            self.__egress_resolved = True
        return self.__proxy_url

    def __setup_selenium_driver(self):
        proxy_url = self.__ensure_egress()
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        if proxy_url:
            chrome_options.add_argument(f"--proxy-server={proxy_url}")
        # Suppress automation signals that bot-detection (e.g. Akamai) checks for
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        self.__driver = webdriver.Chrome(options=chrome_options)
        # A page that never fires its load event raises TimeoutException
        # instead of hanging the worker past the adapter's budget.
        self.__driver.set_page_load_timeout(self.PAGE_LOAD_TIMEOUT)
        self.__driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            },
        )
        # Chrome's own string is the honest answer on this channel — we really
        # are Chrome — so it is left alone by default, and the identifying
        # string is deliberately NOT sent here (it gains nothing on any
        # council and melbourne 403s anything not browser-shaped).
        #
        # The one exception is opt-in per scraper: headless Chrome announces
        # itself as "HeadlessChrome", and a few WAFs reject that token on
        # sight. Stripping it is off by default because it is not free.
        # Measured by running each Selenium-channel scraper both ways
        # (2026-08-20), meetings returned:
        #
        #   scraper       headless UA   de-headlessed
        #   banyule                73     10   <- year-filter postbacks break
        #   campbelltown           95     95
        #   darebin                84     84
        #   melbourne               0    224   <- 403 without it
        #   strathfield            97     97
        #
        # So this is melbourne's fix, not a global improvement. Reachability
        # alone would have said all five were fine either way — banyule loads
        # its listing page and then fails on the interaction.
        if self.strip_headless_user_agent:
            user_agent = self.__driver.execute_script("return navigator.userAgent")
            if "Headless" in user_agent:
                self.__driver.execute_cdp_cmd(
                    "Network.setUserAgentOverride",
                    {"userAgent": user_agent.replace("Headless", "")},
                )

    def get_selenium_driver(self):
        if not self.__driver:
            self.__setup_selenium_driver()
        return self.__driver

    def fetch_with_requests(self, url, method="GET", **kwargs):
        # Defaulted here, below the RecordingFetcher, not in the scraper or
        # the recorder: cassette keys are built from the kwargs a scraper
        # passes, so adding it any higher would change every key and make
        # every recorded fixture miss. A scraper may still pass its own.
        kwargs.setdefault("timeout", self.__timeout)
        if self.__ensure_egress():
            # Passed per request as well as set on the session, because
            # requests lets an HTTPS_PROXY in the environment override the
            # session's proxies but not a request's own.
            kwargs.setdefault("proxies", dict(self.__session.proxies))
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            self.__throttle(url)
            if method.upper() == "POST":
                response = self.__session.post(url, **kwargs)
            else:
                response = self.__session.get(url, **kwargs)

            if response.status_code not in self.RETRY_STATUSES:
                response.raise_for_status()
                return response.text

            last_error = requests.HTTPError(
                f"{response.status_code} for {url}", response=response
            )
            if response.status_code == 403:
                # Not a transient failure, so retrying is pointless. What it
                # means now that we identify ourselves is narrower than it used
                # to be — see BlockedByWAF.
                last_error = BlockedByWAF(url, self.user_agent)
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

    def restart_driver(self) -> None:
        if self.__driver:
            try:
                self.__driver.quit()
            except Exception:
                # Already gone — quitting a dead session raises, and the point
                # of this call is to recover from exactly that.
                pass
        self.__driver = None

    def close(self) -> None:
        if not self.__driver:
            return
        try:
            self.__driver.quit()
        except Exception as e:
            # A session that has already died cannot be quit over, and Chrome
            # would outlive it. Signal the processes directly instead.
            self.__logger.warning(f"Could not quit the browser cleanly: {e}")
            self.abandon()
        finally:
            # Forgotten either way, so a later abandon() never signals a PID
            # that chromedriver no longer owns.
            self.__driver = None

    def abandon(self) -> None:
        # The adapter leaves with os._exit when its budget runs out, which
        # skips Selenium's own cleanup, and chromedriver dying does not take
        # its Chrome with it: both stayed alive after the run, reparented to
        # init. So signal Chrome (chromedriver's children; Chrome takes its
        # own renderers down) and then chromedriver. SIGTERM only, never a
        # wait—this runs on the way out of a process that is already late.
        process = getattr(getattr(self.__driver, "service", None), "process", None)
        if process is None:
            return
        try:
            children = subprocess.run(
                ["pgrep", "-P", str(process.pid)],
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.split()
        except Exception as e:
            self.__logger.warning(f"Could not list chromedriver's children: {e}")
            children = []
        for pid in [*children, str(process.pid)]:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass


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

    # Set on the subclass only for a council whose WAF refuses an identifying
    # client — `BROWSER_USER_AGENT`, verified against that council. Leave it
    # None everywhere else; see `resolve_user_agent` and #142.
    user_agent: Optional[str] = None

    # Set on the subclass for a council that rejects the "HeadlessChrome"
    # token in Chrome's User-Agent. Verify by running the scraper both ways
    # and comparing meetings returned — it costs banyule most of its history.
    strip_headless_user_agent: bool = False

    # "residential" for a council that refuses GitHub's runners whatever we
    # send: its requests then go through RESIDENTIAL_PROXY_URL, and with that
    # unset it fails by name with EgressUnavailable. Set it only after probing
    # the council from a runner—a home connection proves nothing. See
    # AGENTS.md, "Councils that block GitHub's runners".
    egress: str = "direct"

    # Roughly how long one production run (a single `--years` year, from the
    # runner) takes, in seconds. main.py uses it only to order dispatch:
    # longest first, so a slow scraper starts at t=0 rather than after the
    # pool has drained the cheap ones and runs on alone towards the 600 s
    # kill. Nothing enforces it. Leave the default unless a measured run is
    # well above it, and then set the measured number, not a guess.
    expected_seconds: float = 5.0

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
        self.fetcher = DefaultFetcher(
            user_agent=self.user_agent,
            strip_headless_user_agent=self.strip_headless_user_agent,
            egress=self.egress,
            council=self.council_name,
        )

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

        # Year pages that raised, kept so that a council whose every year
        # failed can fail too. See the handler at the bottom of the loop.
        failures: list[Exception] = []

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

            except EgressUnavailable:
                # Not a bad year page: no year can be fetched, and wrapping
                # it in the every-year-failed RuntimeError below would hide
                # the one error type that says what to fix.
                raise
            except Exception as e:
                # One bad year should not cost the others: a full-history
                # walk asks for years the site may not serve. But this used
                # to log at DEBUG, which hid a blocked or stalled host
                # completely—and production asks for one year only, so a
                # requests.Timeout here came back as an ok council with 0
                # meetings. Warn, and fail the council once every year has
                # failed (below).
                self.logger.warning(
                    f"{self.council_name}: failed to fetch meetings for {year}: {e}"
                )
                failures.append(e)
                continue

        if failures and len(failures) == len(years_to_try):
            raise RuntimeError(
                f"{self.council_name}: every InfoCouncil year page failed "
                f"({len(failures)} of {len(years_to_try)})"
            ) from failures[-1]

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


class DocsPublishedScraper(BaseScraper):
    """Councils publishing through docspublished.com.au (DocAssembler).

    The published page is an Angular app that renders nothing without
    JavaScript, but everything behind it is JSON, so this needs no browser.
    A subclass supplies only the publishing slug — the path segment in the
    public URL.

    **The viewer URL is not the document.** `/<slug>/document/<uuid>` is the
    SPA shell: it answers 200 `text/html` and fetches the PDF client-side, so
    anything downstream expecting a PDF gets ~10 KB of Angular instead. The
    shell is also what *unknown* paths under the slug return, so getting this
    wrong fails silently rather than 404ing. The real document lives in Azure
    blob storage and is composed in three steps:

    1. `/api/organisation/<slug>` → `Key`, the tenant's blob path segment.
       `Key` and `Id` are different UUIDs: `Id` keys the document list, `Key`
       keys the storage path, and swapping them yields URLs that 404.
    2. `/api/documents/<Id>` → per meeting, the assembled agenda and minutes
       as `<kind>AssembledDocFolderName` and `<kind>DocumentFilePath`.
    3. `<container>/<Key>/<folder>/<file>` plus the container's read-only SAS
       token, which the portal ships in its JS bundle (see `_storage_config`).

    The filenames the API reports cannot be trusted verbatim. Blob names are
    byte-exact, and DocAssembler's stored path sometimes disagrees with what
    it actually wrote — always in whitespace, always in the same direction:
    the blob has a run of spaces where the API reports one. Ten of Northern
    Beaches' 269 documents are affected, and every one of them 404s. Both the
    list and the per-document endpoint report the collapsed name, so there is
    no better field to read; the only source of truth is the container
    listing, which the same SAS token makes readable. `_stored_names` reads it
    once per council and `_document_url` reconciles against it, which also
    drops the occasional document the API lists but nobody ever uploaded (two
    at Parramatta).
    """

    API_ROOT = "https://api.docassembler.com.au/api"
    PORTAL_ROOT = "https://docspublished.com.au"

    # Azure caps a listing page at 5000 blobs; Parramatta needs three pages.
    LISTING_PAGE_SIZE = 5000

    # Set on the subclass. The organisation id is deliberately not a class
    # attribute: `Key` has to be fetched anyway and `Id` comes back on the
    # same response, so hardcoding the id bought nothing and left two values
    # to keep in step.
    publishing_slug: str = ""

    BUNDLE_REGEX = re.compile(r'src="([^"]*main-[A-Za-z0-9]+\.js)"')
    BASE_HREF_REGEX = re.compile(r'<base[^>]+href="([^"]*)"')
    BLOB_CONFIG_REGEX = re.compile(
        r'azureConnectionString:"(?P<base>[^"]+)"'
        r',azureContainerName:"(?P<container>[^"]+)"'
        r',azureSasToken:"(?P<sas>[^"]+)"'
    )

    def __init__(self, council_name: str, state: str):
        super().__init__(
            council_name,
            state,
            f"{self.PORTAL_ROOT}/{self.publishing_slug}",
        )

    def scraper(self) -> list[ScraperReturn]:
        years_filter = getattr(self, "years_filter", None)

        # Each of these three lookups is required: without the organisation,
        # the storage token or the document list there is nothing to emit.
        # A failure raises rather than returning [], because run_scraper
        # reports [] as an ok council with 0 meetings and the ingest records
        # that as a successful scrape. api.docassembler.com.au is the host
        # that once stalled a run for 12+ minutes; now that requests time
        # out, a stall must surface as a failed council, not a quiet one.
        organisation = self._get_json(
            f"{self.API_ROOT}/organisation/{self.publishing_slug}"
        )
        if not organisation:
            raise RuntimeError(
                f"No DocAssembler organisation for {self.publishing_slug}"
            )

        storage = self._storage_config()
        if not storage:
            raise RuntimeError("Could not read the DocAssembler storage settings")

        tenant_key = organisation["Key"]
        stored = self._stored_names(storage, tenant_key)
        documents = self._get_json(f"{self.API_ROOT}/documents/{organisation['Id']}")
        if documents is None:
            raise RuntimeError(
                f"DocAssembler returned no document list for {self.publishing_slug}"
            )
        if not documents:
            self.logger.warning(f"{self.council_name} scraper found no meetings")
            return []

        tz = pytz.timezone(TIMEZONES_BY_STATE[self.state.upper()])
        results = []

        for doc in documents:
            meeting_date_str = doc.get("MeetingDate")
            if not meeting_date_str:
                continue

            # MeetingDate is UTC without an offset, so the local date can
            # differ from the UTC one — a 10:30am Sydney meeting is stamped
            # 23:30 the previous day. Converting is what makes the data line
            # up: meetings then start at the hours the council publishes, and
            # the local date agrees with the date in the document filenames.
            try:
                meeting_dt = (
                    datetime.datetime.fromisoformat(meeting_date_str)
                    .replace(tzinfo=datetime.timezone.utc)
                    .astimezone(tz)
                )
            except ValueError:
                self.logger.warning(f"Unparseable MeetingDate {meeting_date_str!r}")
                continue

            if years_filter and meeting_dt.year not in years_filter:
                continue

            papers = {}
            for kind in ("Agenda", "Minutes"):
                url = self._document_url(
                    storage,
                    tenant_key,
                    stored,
                    doc.get(f"{kind}AssembledDocFolderName"),
                    doc.get(f"{kind}DocumentFilePath"),
                )
                if not url:
                    continue
                # Councils occasionally publish a Word agenda. Report it as
                # the HTML rendition so the PDF fields only ever hold a PDF.
                suffix = "pdf" if url.split("?")[0].lower().endswith(".pdf") else "html"
                papers[f"{kind.lower()}_{suffix}"] = url

            # A meeting can be listed before either paper is published.
            if not papers:
                continue

            # The viewer page for the document we linked: the page a human
            # would land on, and the one identifier that survives a SAS-token
            # rotation. The blob URL can be re-resolved from this UUID,
            # whereas the signed URL alone goes permanently dead.
            viewer_id = doc.get("AgendaDocumentId") or doc.get("MinutesDocumentId")
            agenda_url = papers.get("agenda_pdf")
            minutes_url = papers.get("minutes_pdf")

            results.append(
                ScraperReturn(
                    name=doc.get("MeetingType") or doc.get("DocumentTitle"),
                    date=meeting_dt.strftime("%Y-%m-%d"),
                    time=meeting_dt.strftime("%I:%M %p").lstrip("0"),
                    webpage_url=(
                        f"{self.base_url}/document/{viewer_id}"
                        if viewer_id
                        else self.base_url
                    ),
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    agenda_html_url=papers.get("agenda_html"),
                    minutes_html_url=papers.get("minutes_html"),
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            self.logger.info(f"{self.council_name} scraper found no meetings")
        else:
            self.logger.info(
                f"{self.council_name} scraper found {len(results)} meetings"
            )

        return results

    def _get_json(self, url: str):
        """Fetch JSON through the fetcher so runs stay recordable.

        Fetch and decode errors propagate: the caller has no fallback for
        either call this serves, so catching them here only turned a timeout
        or a 5xx into an empty result.
        """
        body = self.fetcher.fetch_with_requests(url)
        return json.loads(body) if body else None

    def _storage_config(self) -> Optional[dict]:
        """Read the blob storage settings out of the portal's JS bundle.

        The container is not anonymously readable — without the SAS token
        every blob answers `404 BlobNotFound` — and the token is public only
        in the sense that the portal hands it to every visitor. It carries no
        expiry of its own but is bound to a stored access policy, so the
        operator can rotate or revoke it server-side at any time. Hardcoding
        it would work right up until it silently stopped, so it is read from
        the bundle on each run. The bundle name carries a build hash that
        changes on every deploy, so that too is discovered from the page.

        A fetch failure propagates; the caller has no fallback for a
        missing token. A page that loads but no longer matches the regexes
        returns None, and the caller raises on that too.
        """
        shell = self.fetcher.fetch_with_requests(self.base_url)
        bundle_match = self.BUNDLE_REGEX.search(shell)
        if not bundle_match:
            self.logger.error("Could not find the DocAssembler JS bundle")
            return None

        # The portal is an Angular app served with <base href="/">, so its
        # relative script tags resolve against the site root, not the
        # council path. Getting this wrong is quiet rather than loud:
        # unknown paths return the app shell with a 200 instead of a 404.
        base_href = self.BASE_HREF_REGEX.search(shell)
        base_url = urllib.parse.urljoin(
            self.base_url, base_href.group(1) if base_href else "/"
        )

        bundle = self.fetcher.fetch_with_requests(
            urllib.parse.urljoin(base_url, bundle_match.group(1))
        )
        config_match = self.BLOB_CONFIG_REGEX.search(bundle)
        if not config_match:
            self.logger.error("Could not find the storage settings in the bundle")
            return None

        return config_match.groupdict()

    def _stored_names(self, storage: dict, tenant_key: str) -> Optional[dict]:
        """List the council's blobs, as `{folder: [filename, ...]}`.

        Returns None when the listing cannot be read, which the caller treats
        as "trust the API" rather than "emit nothing": a listing failure
        should cost the handful of misnamed documents, not the whole council.
        """
        names: dict[str, list[str]] = {}
        marker = ""

        try:
            while True:
                query = urllib.parse.urlencode(
                    {
                        "restype": "container",
                        "comp": "list",
                        "prefix": f"{tenant_key}/",
                        "maxresults": self.LISTING_PAGE_SIZE,
                        **({"marker": marker} if marker else {}),
                    }
                )
                body = self.fetcher.fetch_with_requests(
                    f"{storage['base']}/{storage['container']}{storage['sas']}&{query}"
                )
                listing = ElementTree.fromstring(body)

                for element in listing.iter("Name"):
                    # "<tenant>/<folder>/<file>". Deeper paths are the
                    # per-agenda-item PDFs, which we do not link.
                    parts = (element.text or "").split("/")
                    if len(parts) == 3:
                        names.setdefault(parts[1], []).append(parts[2])

                marker = (listing.findtext("NextMarker") or "").strip()
                if not marker:
                    return names
        except Exception as e:
            self.logger.warning(
                f"Could not list DocAssembler storage for {self.council_name}; "
                f"falling back to the filenames the API reports: {e}"
            )
            return None

    @staticmethod
    def _collapse(name: str) -> str:
        return re.sub(r"\s+", " ", name)

    def _document_url(
        self,
        storage: dict,
        tenant_key: str,
        stored: Optional[dict],
        folder_name: Optional[str],
        file_path: Optional[str],
    ) -> Optional[str]:
        """Build the storage URL for one document, mirroring the portal."""
        if not folder_name or not file_path:
            return None

        if stored is None:
            # No listing to check against, so the API's name is all we have.
            name = file_path
        else:
            in_folder = stored.get(folder_name, ())
            if file_path in in_folder:
                name = file_path
            else:
                collapsed = self._collapse(file_path)
                candidates = [n for n in in_folder if self._collapse(n) == collapsed]
                if len(candidates) == 1:
                    name = candidates[0]
                    self.logger.debug(
                        f"Blob name differs from the API's: {file_path!r} -> {name!r}"
                    )
                else:
                    # Either the document was never uploaded, or two blobs
                    # differ only in whitespace and there is no telling which
                    # the API meant. A URL we know 404s is worse than none.
                    near = f" ({len(candidates)} near matches)" if candidates else ""
                    self.logger.info(
                        f"No stored blob for {folder_name}/{file_path!r}{near}"
                    )
                    return None

        quoted = "/".join(
            urllib.parse.quote(part, safe="")
            for part in (tenant_key, folder_name, name)
        )
        return f"{storage['base']}/{storage['container']}/{quoted}{storage['sas']}"


SCRAPER_REGISTRY: dict[str, BaseScraper] = {}
