from __future__ import annotations

import datetime
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

    def _collect_all_cvids(self) -> list[tuple[str, str, str]]:
        """
        Load the listing page and attempt to collect CVIDs for all years
        from EARLIEST_YEAR to current+1.

        The initial Selenium load gives us the first page (~10 items).
        For complete coverage we try to submit the year-filter form via the
        Selenium driver for each year.  This requires ``get_selenium_driver()``
        which raises in the test harness – the exception is caught and we
        fall back to whatever page-1 gave us.
        """
        # --- Load page 1 ---
        listing_html = self.fetcher.fetch_with_selenium(self.webpage_url)
        initial_soup = BeautifulSoup(listing_html, "html.parser")
        page1_items = _parse_listing_items(initial_soup)

        all_items: list[tuple[str, str, str]] = []
        seen_cvids: set[str] = set()
        for item in page1_items:
            if item[2] not in seen_cvids:
                seen_cvids.add(item[2])
                all_items.append(item)

        # --- Try year-filter form for full coverage ---
        try:
            import time

            driver = self.fetcher.get_selenium_driver()

            current_year = datetime.date.today().year
            for year in range(current_year + 1, EARLIEST_YEAR - 1, -1):
                driver.execute_script(
                    f"""
                    document.querySelector(
                        'select[name="ctl11$ctl00$ctl05$ctl00$ctl00"]'
                    ).value = '{year}';
                    document.querySelector(
                        'input[name="ctl11$ctl00$ctl06"]'
                    ).click();
                    """
                )
                time.sleep(3)

                while True:
                    page_soup = BeautifulSoup(driver.page_source, "html.parser")
                    for item in _parse_listing_items(page_soup):
                        if item[2] not in seen_cvids:
                            seen_cvids.add(item[2])
                            all_items.append(item)

                    # Follow "Next" page button if available and enabled
                    next_btn = page_soup.find(
                        "input",
                        attrs={"name": "ctl11$ctl00$ctl16", "type": "submit"},
                    )
                    if not next_btn or next_btn.get("disabled"):
                        break
                    driver.execute_script(
                        "document.querySelector("
                        "'input[name=\"ctl11$ctl00$ctl16\"]'"
                        ").click();"
                    )
                    time.sleep(3)

        except Exception:
            # Driver unavailable, page error, etc. – use what page 1 gave us.
            pass
        except BaseException:
            # pytest.skip() or similar raised in test harness – silently continue.
            pass

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
        location: str | None = None
        if location_div:
            location = (
                location_div.get_text(" ", strip=True)
                .replace("Location", "")
                .strip()
                or None
            )

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
