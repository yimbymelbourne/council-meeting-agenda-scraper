from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.northsydney.nsw.gov.au"
_LISTING_URL = f"{_BASE_URL}/council-meetings"

# Listing entries link to a numbered meeting page, e.g.
# /council-meetings/304/24-08-2026-council-meeting. The sidebar of that page
# links documents under /ecm/download/, while the body links the individual
# reports that make up the business paper under /ecm/download-meeting-consent/.
# Only the former are the agenda and the minutes.
_MEETING_HREF = re.compile(r"^/council-meetings/\d+/")

# "24/08/2026           Council Meeting" — the site pads the anchor text.
_LISTING_TEXT = re.compile(r"^(\d{2}/\d{2}/\d{4})\s*(.*)$")

# Published on the listing page: "Council meetings start at 7pm and are held
# in Council Chambers." The meeting pages themselves carry neither, so these
# stand in for every meeting rather than being scraped per meeting.
_DEFAULT_TIME = "7:00pm"
_DEFAULT_LOCATION = "Council Chambers"


def _parse_listing_entry(anchor) -> tuple[datetime, str] | None:
    """Return (date, meeting name) for a listing anchor, or None if it is not one."""
    href = anchor.get("href", "")
    if not _MEETING_HREF.match(href):
        return None

    text = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
    match = _LISTING_TEXT.match(text)
    if not match:
        return None

    try:
        date = datetime.strptime(match.group(1), "%d/%m/%Y")
    except ValueError:
        return None

    return date, match.group(2).strip()


@register_scraper
class NorthSydneyScraper(BaseScraper):
    def __init__(self):
        council = "north_sydney"
        state = "NSW"
        super().__init__(council, state, _BASE_URL)
        self.default_time = _DEFAULT_TIME
        self.default_location = _DEFAULT_LOCATION

    # ------------------------------------------------------------------
    # Step 1: walk the paginated listing
    # ------------------------------------------------------------------

    def _next_page_url(self, soup: BeautifulSoup) -> str | None:
        link = soup.select_one("li.pagination__item--next a.pagination__link")
        return urljoin(_BASE_URL, link["href"]) if link and link.get("href") else None

    def _collect_meetings(self) -> list[tuple[datetime, str, str]]:
        """Return (date, name, meeting page URL) for every meeting worth fetching.

        The listing is one long run of meetings newest first — the site's own
        year filter is inert (``?year=2024`` returns the unfiltered first page),
        so pagination is the only way through it. Because the order is strictly
        descending, a page whose every entry predates ``EARLIEST_YEAR`` means
        the rest of the archive does too, and there is nothing left to page to.
        """
        meetings: list[tuple[datetime, str, str]] = []
        seen_urls: set[str] = set()
        url: str | None = _LISTING_URL

        while url and url not in seen_urls:
            seen_urls.add(url)
            soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

            entries = 0
            in_range = 0
            for anchor in soup.find_all("a", class_="listing__link", href=True):
                parsed = _parse_listing_entry(anchor)
                if not parsed:
                    continue
                entries += 1
                date, name = parsed
                if date.year < EARLIEST_YEAR:
                    continue
                in_range += 1
                meetings.append((date, name, urljoin(_BASE_URL, anchor["href"])))

            if entries and not in_range:
                break

            url = self._next_page_url(soup)

        return meetings

    # ------------------------------------------------------------------
    # Step 2: read the agenda and minutes off each meeting page
    # ------------------------------------------------------------------

    def _documents(self, soup: BeautifulSoup) -> tuple[str | None, str | None]:
        """Return (agenda URL, minutes URL) from a meeting page's sidebar.

        The sidebar is a run of ``<h2>Agenda 24 August 2026</h2>`` followed by a
        list holding the link. The link text is unreliable — recent meetings
        label it "Agenda", older ones "Agenda - 28 June 2021" — so the heading
        above the list is what identifies the document.

        A meeting page can carry neither: the extraordinary meetings of
        1 July 2026 and 1 March 2023, among others, have an empty sidebar and
        no documents anywhere on the page.
        """
        agenda_url = minutes_url = None

        for aside in soup.find_all("div", class_="aside--sidebar"):
            for heading in aside.find_all("h2"):
                # Skip the <h2 class="listing__heading"> wrapping each link.
                if heading.get("class"):
                    continue

                label = heading.get_text(" ", strip=True).lower()
                document_list = heading.find_next_sibling("ul")
                if not document_list:
                    continue

                link = document_list.find("a", class_="listing__link", href=True)
                if not link:
                    continue

                url = urljoin(_BASE_URL, link["href"])
                if label.startswith("agenda") and not agenda_url:
                    agenda_url = url
                elif label.startswith("minutes") and not minutes_url:
                    minutes_url = url

        return agenda_url, minutes_url

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        meetings = self._collect_meetings()
        self.logger.info(f"Found {len(meetings)} meetings in the listing")

        results: list[ScraperReturn] = []
        for date, name, meeting_url in meetings:
            try:
                html = self.fetcher.fetch_with_requests(meeting_url)
            except Exception as e:
                self.logger.warning(f"Could not fetch {meeting_url}: {e}")
                continue

            agenda_url, minutes_url = self._documents(
                BeautifulSoup(html, "html.parser")
            )
            if not agenda_url and not minutes_url:
                self.logger.info(f"No agenda or minutes published on {meeting_url}")
                continue

            results.append(
                ScraperReturn(
                    name=name or self.default_name,
                    # dd/mm/yyyy reads as a US date to dateutil, so hand it a
                    # form that cannot be misread.
                    date=date.strftime("%d %B %Y"),
                    time=self.default_time,
                    webpage_url=meeting_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                    location=self.default_location,
                )
            )

        if not results:
            self.logger.warning("No meetings found for North Sydney")
        else:
            self.logger.info(f"Found {len(results)} North Sydney meetings")

        return results
