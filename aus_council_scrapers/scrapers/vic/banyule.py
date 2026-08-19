from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.banyule.vic.gov.au"
_LISTING_URL = (
    "https://www.banyule.vic.gov.au"
    "/About-us/Councillors-and-Council-meetings"
    "/Council-meetings/Council-meeting-agendas-and-minutes"
)

# ASP.NET control names for the year filter on the listing page.
_YEAR_SELECT = "ctl11$ctl00$ctl05$ctl00$ctl00"
_APPLY_BUTTON = "ctl11$ctl00$ctl06"
_NEXT_BUTTON = "ctl11$ctl00$ctl16"

# Stable URL (no cachebuster) so it is uniquely recordable per meeting
_OCSVC_URL = (
    "https://www.banyule.vic.gov.au"
    "/OCServiceHandler.axd"
    "?url=ocsvc/Public/meetings/documentrenderer"
    "&keywords="
    "&cvid={cvid}"
)


def _parse_listing_items(soup: BeautifulSoup) -> list[tuple[str, str, str]]:
    """Return list of (date_str, meeting_type, cvid) from a listing page soup."""
    results = []
    for item in soup.find_all("div", class_="accordion-list-item-container"):
        trigger = item.find("a", class_="accordion-trigger")
        if not trigger:
            continue
        cvid = trigger.get("data-cvid", "").strip()
        if not cvid:
            continue
        date_span = item.find("span", class_="minutes-date")
        type_span = item.find("span", class_="meeting-type")
        date_str = date_span.get_text(strip=True) if date_span else ""
        meeting_type = type_span.get_text(strip=True) if type_span else ""
        if date_str and cvid:
            results.append((date_str, meeting_type, cvid))
    return results


def _year_of(date_str: str) -> int | None:
    m = re.search(r"\b(\d{4})\b", date_str)
    return int(m.group(1)) if m else None


def _clean_location(location_div: BeautifulSoup) -> str | None:
    """
    Extract the address text from a ``meeting-address`` div.

    The markup is ``<h3>Location</h3><p>…address… <a>View Map</a></p>``, so the
    heading and the Google Maps link are removed before reading the text –
    otherwise both end up appended to the address.  Banyule separates the
    address parts with ``&nbsp;``, which is collapsed to plain spaces.

    Banyule also pastes notices into this div as extra paragraphs::

        <p>Please note: due to technical difficulties, the first half of last
           night's Council meeting isn't available…</p>
        <p>Council Chambers @ Ivanhoe Library…<a>View Map</a></p>

    Reading the whole div would store that apology as the meeting location, so
    when the address can be identified by its map link, only that paragraph is
    used.
    """
    for heading in location_div.find_all("h3"):
        heading.decompose()

    # The paragraph holding the map link is the address; anything else in the
    # div is commentary.
    address = location_div
    for paragraph in location_div.find_all("p"):
        if paragraph.find("a", href=re.compile(r"maps\.google\.com")):
            address = paragraph
            break

    for anchor in address.find_all("a", href=True):
        if "maps.google.com" in anchor["href"] or re.fullmatch(
            r"view map", anchor.get_text(strip=True), re.IGNORECASE
        ):
            anchor.decompose()

    return re.sub(r"\s+", " ", address.get_text(" ", strip=True)).strip() or None


@register_scraper
class BanyuleScraper(BaseScraper):
    def __init__(self):
        council = "banyule"
        state = "VIC"
        base_url = _BASE_URL
        self.webpage_url = _LISTING_URL
        super().__init__(council, state, base_url)

    # ------------------------------------------------------------------
    # Step 1: collect meeting CVIDs from the listing page
    # ------------------------------------------------------------------

    def _offered_years(self, soup: BeautifulSoup) -> list[str]:
        """The years Banyule's own filter offers, newest first.

        Asking for a year the dropdown does not list does nothing useful:
        assigning an absent value to a ``<select>`` silently leaves it on
        whatever was selected, so the "filtered" request returns the unfiltered
        listing. The previous code counted up to ``current_year + 1``, which is
        never an option, and its first pass was therefore an accidental
        unfiltered crawl. Reading the options makes that pass deliberate.
        """
        select = soup.find("select", attrs={"name": _YEAR_SELECT})
        years = []
        for option in select.find_all("option") if select else []:
            label = option.get_text(strip=True)
            if label.isdigit() and len(label) == 4 and int(label) >= EARLIEST_YEAR:
                years.append(option.get("value") or label)
        return years

    def _page_through(
        self, driver, seen_cvids: set[str], all_items: list[tuple[str, str, str]]
    ) -> None:
        """Collect every meeting in the listing as currently filtered."""
        while True:
            page_soup = BeautifulSoup(driver.page_source, "html.parser")
            for item in _parse_listing_items(page_soup):
                if item[2] not in seen_cvids:
                    seen_cvids.add(item[2])
                    all_items.append(item)

            next_btn = page_soup.find(
                "input", attrs={"name": _NEXT_BUTTON, "type": "submit"}
            )
            if not next_btn or next_btn.get("disabled"):
                return
            driver.execute_script(
                f"document.querySelector('input[name=\"{_NEXT_BUTTON}\"]').click();"
            )
            self.fetcher.sleep(3)

    def _collect_all_cvids(self) -> list[tuple[str, str, str]]:
        """
        Collect meeting CVIDs from the unfiltered listing and from each year
        the site's own filter offers.

        Note that Banyule offers years in the dropdown that hold no meetings:
        as of August 2026 it lists 2017-2026, but 2017-2021 each return only a
        sticky "next meeting" element. Its published history genuinely starts
        in 2022, so the shortfall against EARLIEST_YEAR is the council's, not a
        gap in this scraper — there is nothing here to fix.
        """
        listing_html = self.fetcher.fetch_with_selenium(self.webpage_url)
        initial_soup = BeautifulSoup(listing_html, "html.parser")

        all_items: list[tuple[str, str, str]] = []
        seen_cvids: set[str] = set()

        try:
            driver = self.fetcher.get_selenium_driver()

            # The unfiltered listing first — it carries everything, and paging
            # it is cheaper than trusting the filter to be exhaustive.
            self._page_through(driver, seen_cvids, all_items)

            for year in self._offered_years(initial_soup):
                driver.execute_script(
                    f"""
                    document.querySelector('select[name="{_YEAR_SELECT}"]')
                        .value = '{year}';
                    document.querySelector('input[name="{_APPLY_BUTTON}"]').click();
                    """
                )
                self.fetcher.sleep(3)
                self._page_through(driver, seen_cvids, all_items)

        except Exception:
            # The year filter is how this scraper reaches anything beyond the
            # ~10 meetings on page 1, so losing it is a real degradation, not
            # a detail. Log it loudly and keep the partial result rather than
            # dropping the meetings we did get.
            self.logger.exception(
                "Banyule listing pagination failed; keeping the "
                f"{len(all_items)} meetings collected so far."
            )
            if not all_items:
                all_items = _parse_listing_items(initial_soup)

        # Keep only years >= EARLIEST_YEAR
        return [
            item
            for item in all_items
            if (_year_of(item[0]) or 0) >= EARLIEST_YEAR
        ]

    # ------------------------------------------------------------------
    # Step 2: fetch individual meeting content via ocsvc API
    # ------------------------------------------------------------------

    def _fetch_ocsvc(self, cvid: str) -> BeautifulSoup | None:
        """
        Fetch the meeting document content via the OCServiceHandler AJAX endpoint.
        Uses fetch_with_selenium so the browser session / cookies are valid.
        The URL is stable (no changing cachebuster) and unique per cvid so it
        is correctly recorded and replayed by the test infrastructure.
        """
        url = _OCSVC_URL.format(cvid=cvid)
        try:
            raw = self.fetcher.fetch_with_selenium(url)
        except Exception as e:
            self.logger.warning(f"Error fetching ocsvc for cvid {cvid}: {e}")
            return None

        # The browser wraps the JSON in <html><body><pre>…</pre></body></html>
        # Extract the raw JSON string.
        soup = BeautifulSoup(raw, "html.parser")
        pre = soup.find("pre")
        json_text = pre.get_text() if pre else raw
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError:
            # Some browsers render JSON without <pre> – try the whole text
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                self.logger.warning(f"Could not parse ocsvc JSON for cvid {cvid}")
                return None

        html = data.get("html", "")
        return BeautifulSoup(html, "html.parser") if html else None

    def _extract_doc_url(self, section: BeautifulSoup) -> str | None:
        for a in section.find_all("a", href=True):
            href = a["href"].strip()
            if href:
                return urljoin(self.base_url, href)
        return None

    def _build_scraper_return(
        self,
        content_soup: BeautifulSoup,
        date_str: str,
        meeting_type: str,
    ) -> ScraperReturn | None:
        # Time
        time_div = content_soup.find("div", class_="meeting-time")
        time_val: str | None = None
        if time_div:
            raw_time = (
                time_div.get_text(" ", strip=True).replace("Time", "").strip()
            )
            m = re.search(self.time_regex, raw_time)
            time_val = m.group() if m else raw_time or None

        # Location
        location_div = content_soup.find("div", class_="meeting-address")
        location = _clean_location(location_div) if location_div else None

        # Agenda / minutes from meeting-document divs
        agenda_url: str | None = None
        minutes_url: str | None = None
        for doc_div in content_soup.find_all("div", class_="meeting-document"):
            h3 = doc_div.find("h3")
            if not h3:
                continue
            heading = h3.get_text(strip=True).lower()
            doc_url = self._extract_doc_url(doc_div)
            if not doc_url:
                continue
            if heading == "agenda" and not agenda_url:
                agenda_url = doc_url
            elif heading == "minutes" and not minutes_url:
                minutes_url = doc_url
            elif heading == "confirmed minutes" and not minutes_url:
                minutes_url = doc_url

        if not agenda_url and not minutes_url:
            return None

        return ScraperReturn(
            name=meeting_type or self.default_name,
            date=date_str,
            time=time_val,
            webpage_url=self.webpage_url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url,
            location=location,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        items = self._collect_all_cvids()
        self.logger.info(f"Found {len(items)} meeting entries to process")

        results: list[ScraperReturn] = []
        for date_str, meeting_type, cvid in items:
            content_soup = self._fetch_ocsvc(cvid)
            if content_soup is None:
                continue
            record = self._build_scraper_return(content_soup, date_str, meeting_type)
            if record:
                results.append(record)

        if not results:
            self.logger.warning("No meetings found for Banyule")
        else:
            self.logger.info(f"Found {len(results)} Banyule meetings")

        return results
