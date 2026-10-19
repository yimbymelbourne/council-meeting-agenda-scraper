import datetime
import json
import re
from typing import Optional
from urllib.parse import unquote, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from dateutil.parser import parse as parse_date
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://balranald.nsw.gov.au"
_LISTING_URL = f"{_BASE_URL}/business/council-documents/council-agenda/"
_AJAX_URL = f"{_BASE_URL}/wp-admin/admin-ajax.php"

# Balranald Shire Council lists its meetings in a JetEngine listing grid on
# WordPress: twenty a page, newest first, back to 2013. Each item is a
# meeting with its date ("October 20, 2026"), its type ("Ordinary Meeting",
# "Extraordinary Meeting") and columns of links: Agenda plus "Part 1".."Part
# n" attachment books; Minutes; Facebook Live; and an "Other" column of
# submissions and correspondence. Only the links labelled Agenda and Minutes
# are papers.
#
# Page 1 is in the HTML and reaches back about seventeen months, so one
# production year is one page load. Later pages come from the grid's "Load
# More" button, a POST to admin-ajax.php carrying the query and widget
# settings the page embeds in `data-nav`—signed by the site, so they are read
# from the page rather than written here. Paging stops once a page reaches
# back before the earliest year wanted. robots.txt disallows nothing.
#
# The REST API has every meeting as a `council-meetings` post but no
# document fields, and the per-meeting pages carry no links, so the grid is
# the only place agenda and minutes are tied to a meeting.
#
# Links are hand-entered per meeting and a few are wrong: the 22 July 2025
# meeting's minutes link is the 15 July minutes. A filename naming a full
# date other than the meeting's is left out. Scanned minutes
# ("Scanned-Document-18022026151619-0001.pdf") carry only a scan stamp,
# which is not read.
#
# The site is on Kinsta behind Cloudflare, and Kinsta's bot check decides
# who gets the page. On 20 Oct 2026, from a home connection, the identifying
# requests client got the listing and five Load More pages, then about an
# hour later got 403 "Checking your browser" for the listing, the papers
# and robots.txt alike. Headless Chrome got the same 403 page. Chrome with
# "HeadlessChrome" stripped from its User-Agent got the listing and, from
# inside the page, the papers as application/pdf. So the scraper drives
# Chrome, and the Load More POST is sent from the page with XMLHttpRequest:
# it then carries the browser's own cookies and headers. How a GitHub runner
# fares is unmeasured.
_MONTH_NAMES = [datetime.date(2000, m, 1).strftime("%B").lower() for m in range(1, 13)]
_FILENAME_DATE = re.compile(
    r"(?<!\d)(\d{1,2})-(" + "|".join(_MONTH_NAMES) + r")-(\d{4})(?!\d)", re.IGNORECASE
)
_EXTRAORDINARY = re.compile(r"extra-?ordinary|extraodinary", re.IGNORECASE)


def _filename(url: str) -> str:
    return unquote(urlparse(url).path.rsplit("/", 1)[-1])


def _named_date(url: str) -> Optional[datetime.date]:
    match = _FILENAME_DATE.search(_filename(url))
    if not match:
        return None
    try:
        return datetime.date(
            int(match[3]), _MONTH_NAMES.index(match[2].lower()) + 1, int(match[1])
        )
    except ValueError:
        return None


def _flatten(prefix: str, value, out: list) -> None:
    """Encode nested settings the way jQuery.param does, which is what the
    Load More button sends: query[post_status][]=publish and so on."""
    if isinstance(value, dict):
        for key, item in value.items():
            _flatten(f"{prefix}[{key}]", item, out)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            nested = isinstance(item, (dict, list))
            _flatten(f"{prefix}[{index}]" if nested else f"{prefix}[]", item, out)
    elif isinstance(value, bool):
        out.append((prefix, "true" if value else "false"))
    elif value is None:
        out.append((prefix, ""))
    else:
        out.append((prefix, str(value)))


# The grid's container; Kinsta's challenge page does not have it.
_GRID = "div.jet-listing-grid__items[data-nav]"

# Sends one Load More POST from inside the page and leaves the status and
# body in a textarea for page_source to read back. (A cassette records what
# the page shows, not what a script returns.) Synchronous, so the answer is
# there when execute_script returns. The textarea replaces the page, whose
# settings were already read, so each recorded page_source is one response
# rather than the whole listing again.
_LOAD_MORE_SCRIPT = """
var request = new XMLHttpRequest();
request.open('POST', %s, false);
request.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded; charset=UTF-8');
request.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
request.send(%s);
var out = document.createElement('textarea');
out.id = 'load-more-response';
out.textContent = request.status + '\\n' + request.responseText;
document.body.replaceChildren(out);
"""


@register_scraper
class BalranaldScraper(BaseScraper):
    # Kinsta's bot check refuses the "HeadlessChrome" token; see above.
    strip_headless_user_agent = True

    def __init__(self):
        super().__init__("balranald", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        earliest = min(wanted)

        html = self.fetcher.fetch_with_selenium(
            _LISTING_URL,
            wait_time=30,
            wait_condition=EC.presence_of_element_located((By.CSS_SELECTOR, _GRID)),
        )
        soup = BeautifulSoup(html, "html.parser")
        grid = soup.select_one(_GRID)
        if grid is None:
            raise RuntimeError(f"{self.council_name}: no listing grid at {_LISTING_URL}")

        results: list[ScraperReturn] = []
        oldest = self._read_items(soup, wanted, results)

        pages = int(grid.get("data-pages") or 1)
        page = 1
        driver = None
        while page < pages and oldest is not None and oldest.year >= earliest:
            page += 1
            # One driver handle for every page: it is the browser that
            # already holds the listing, and replay hands each handle the
            # recording from the start.
            driver = driver or self.fetcher.get_selenium_driver()
            html = self._load_more(driver, grid, page)
            oldest = self._read_items(BeautifulSoup(html, "html.parser"), wanted, results)

        if not results:
            self.logger.warning(
                f"{self.council_name}: no meetings with papers for {sorted(wanted)} "
                f"at {_LISTING_URL}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    def _load_more(self, driver, grid: Tag, page: int) -> str:
        nav = json.loads(grid["data-nav"])
        widget = grid.find_parent(class_="elementor-widget-jet-listing-grid")
        queried = grid.get("data-queried-id", "")
        post_id = queried.split("|", 1)[0]
        data: list[tuple[str, str]] = [
            ("action", "jet_engine_ajax"),
            ("handler", "listing_load_more"),
        ]
        _flatten("query", nav["query"], data)
        _flatten("widget_settings", nav["widget_settings"], data)
        data += [
            ("page_settings[post_id]", post_id),
            ("page_settings[queried_id]", queried),
            ("page_settings[element_id]", widget.get("data-id", "") if widget else ""),
            ("page_settings[page]", str(page)),
            ("listing_type", "elementor"),
            ("isEditMode", "false"),
        ]
        driver.execute_script(
            _LOAD_MORE_SCRIPT % (json.dumps(_AJAX_URL), json.dumps(urlencode(data)))
        )
        out = BeautifulSoup(driver.page_source, "html.parser").find(id="load-more-response")
        status, _, body = (out.get_text() if out else "").partition("\n")
        try:
            if status.strip() != "200":
                raise ValueError(f"HTTP {status.strip() or 'nothing'}")
            return json.loads(body)["data"]["html"]
        except (ValueError, KeyError, TypeError) as error:
            # A page we were told exists and could not read: the history
            # would be silently short, so fail instead.
            raise RuntimeError(
                f"{self.council_name}: Load More page {page} returned no listing ({error})"
            ) from error

    def _read_items(
        self, soup: BeautifulSoup, wanted: set[int], results: list
    ) -> Optional[datetime.date]:
        """Append the wanted meetings on one page; return its oldest date."""
        oldest = None
        for item in soup.select("div.jet-listing-grid__item"):
            record, meeting_date = self._item(item)
            if meeting_date is None:
                continue
            oldest = meeting_date if oldest is None else min(oldest, meeting_date)
            if record is not None and meeting_date.year in wanted:
                results.append(record)
        return oldest

    def _item(self, item: Tag):
        columns = item.select("div.elementor-top-column")
        if len(columns) < 2:
            return None, None
        date_text = columns[0].get_text(" ", strip=True)
        try:
            meeting_date = parse_date(date_text).date()
        except (ValueError, OverflowError):
            self.logger.warning(f"{self.council_name}: unparseable date {date_text!r}")
            return None, None
        meeting_type = re.sub(r"\s+", " ", columns[1].get_text(" ", strip=True)) or "Council Meeting"

        agenda_url = minutes_url = None
        for link in item.find_all("a", href=True):
            label = link.get_text(" ", strip=True).lower()
            if label not in ("agenda", "minutes"):
                continue
            url = urljoin(_LISTING_URL, link["href"].strip())
            if not urlparse(url).path.lower().endswith(".pdf"):
                continue
            named = _named_date(url)
            if named is not None and named != meeting_date:
                self.logger.warning(
                    f"{self.council_name}: {label} linked on the {meeting_date} "
                    f"meeting is {url}, dated {named}; left out"
                )
                continue
            if label == "agenda" and agenda_url is None:
                agenda_url = url
            elif label == "minutes" and minutes_url is None:
                minutes_url = url

        if not agenda_url and not minutes_url:
            return None, meeting_date

        # The 22 July 2025 meeting is filed as Ordinary, but its agenda is
        # "Agenda-Extraordinary-Meetring-22-July-2025.pdf"; the paper's own
        # title wins.
        if (
            meeting_type.lower().startswith("ordinary")
            and agenda_url
            and _EXTRAORDINARY.search(_filename(agenda_url))
        ):
            meeting_type = "Extraordinary Meeting"

        return (
            ScraperReturn(
                name=meeting_type,
                date=meeting_date.isoformat(),
                time=None,
                webpage_url=_LISTING_URL,
                agenda_url=agenda_url,
                minutes_url=minutes_url,
                download_url=agenda_url or minutes_url,
            ),
            meeting_date,
        )
