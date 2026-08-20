from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper

# Past meetings, newest first, ten to a page — every meeting with published
# documents. Upcoming meetings live on the parent page, oldest first; Boroondara
# publishes an agenda about ten days ahead, so the newest agendas appear there
# before the meeting moves across to the past listing.
PAST_MEETINGS_URL = (
    "https://www.boroondara.vic.gov.au/your-council/councillors-and-meetings/"
    "council-and-committee-meetings/past-meeting-minutes-agendas-and-video-recordings"
)
UPCOMING_MEETINGS_URL = (
    "https://www.boroondara.vic.gov.au/your-council/councillors-and-meetings/"
    "council-and-committee-meetings"
)


@register_scraper
class BoroondaraScraper(BaseScraper):
    """Boroondara publishes one Drupal event page per meeting.

    Each event page carries its documents in ``para-downloads`` blocks titled by
    document type, and its start date and time in the add-to-calendar
    ``<var class="atc_date_start">`` — which is the only place on the page the
    time appears in a machine-readable form.
    """

    def __init__(self):
        super().__init__("boroondara", "VIC", "https://www.boroondara.vic.gov.au")
        self.default_location = "8 Inglesby Road, Camberwell, Victoria 3124"

    _MAX_PAGES = 40  # safety net; the past listing is 11 pages

    # Titles look like "Council Meeting - 24 November 2025", "Additional Council
    # Meeting - 20 October 2025", "Council Meeting - 28 October 2024 - CANCELLED".
    _TITLE_DATE_RE = re.compile(
        r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+((?:19|20)\d{2})\b",
        re.I,
    )

    # "08/17/2026 6:30 pm" — month first, and the time is what we are after.
    _ATC_RE = re.compile(
        r"(\d{1,2})/(\d{1,2})/((?:19|20)\d{2})\s+(\d{1,2}:\d{2}\s*[ap]\.?m\.?)", re.I
    )

    def _soup(self, url: str) -> BeautifulSoup:
        # The fetcher throttles per host and backs off on 429 already; a run
        # over ~115 event pages needs nothing more than that.
        return BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

    def _years_filter(self) -> set[int] | None:
        years = getattr(self, "years_filter", None)
        return set(years) if years else None

    # ---------------------------------------------------------------- listings

    def _event_links(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        """Event page URLs from a listing page, in the order they are listed.

        Each entry is an ``h2`` heading link; the "View event" link below it
        points at the same page, so keying on the heading avoids the duplicate.
        """
        urls: list[str] = []
        for a in soup.select("h2 a[href]"):
            href = (a.get("href") or "").strip()
            if "/events/" not in href:
                continue
            title = a.get_text(" ", strip=True)
            if "meeting" not in title.lower():
                continue
            url = urljoin(page_url, href)
            if url not in urls:
                urls.append(url)
        return urls

    def _next_page_url(self, soup: BeautifulSoup, page_url: str) -> str | None:
        """The pager's next link, resolved against the page it was found on.

        The hrefs are query-only (``?page=3``), so they must resolve against the
        current URL rather than the site root.
        """
        a = soup.select_one("li.pager__item--next a[href]")
        if not a:
            a = soup.select_one('a[rel="next"][href]')
        if a and a.get("href"):
            return urljoin(page_url, a["href"])
        return None

    def _listing_event_urls(self, listing_url: str, newest_first: bool) -> list[str]:
        """Walk a paginated listing and collect its event URLs.

        When a year filter is set and the listing runs newest first, stop paging
        once a whole page falls below the earliest year asked for.
        """
        years = self._years_filter()
        urls: list[str] = []
        page_url: str | None = listing_url
        seen_pages: set[str] = set()

        while (
            page_url
            and page_url not in seen_pages
            and len(seen_pages) < self._MAX_PAGES
        ):
            seen_pages.add(page_url)
            soup = self._soup(page_url)

            page_urls = self._event_links(soup, page_url)
            urls.extend(page_urls)

            if years and newest_first and page_urls:
                page_years = {y for u in page_urls if (y := self._year_from_slug(u))}
                if page_years and max(page_years) < min(years):
                    break

            page_url = self._next_page_url(soup, page_url)

        return urls

    def _year_from_slug(self, event_url: str) -> int | None:
        """Year from an event slug, e.g. ``/events/council-meeting-27-july-2026``.

        Used only to decide whether an event page is worth fetching, so the
        authoritative date still comes from the page itself. The day number
        precedes the year, and a slug can carry a "-cancelled" suffix after it,
        so take the last four-digit group rather than the first.
        """
        years = re.findall(r"-((?:19|20)\d{2})(?=-|$)", event_url)
        return int(years[-1]) if years else None

    # ------------------------------------------------------------ event pages

    def _download_blocks(self, soup: BeautifulSoup) -> dict[str, str]:
        """Map each downloads block's title to its first document URL."""
        blocks: dict[str, str] = {}
        for block in soup.select("div.paragraph--type--para-downloads"):
            heading = block.find(["h2", "h3", "h4", "h5", "h6"])
            if not heading:
                continue
            title = heading.get_text(" ", strip=True).strip().lower()
            link = block.select_one("a[href]")
            if title and link and title not in blocks:
                blocks[title] = urljoin(self.base_url, link["href"].strip())
        return blocks

    def _agenda_and_minutes(self, soup: BeautifulSoup) -> tuple[str | None, str | None]:
        blocks = self._download_blocks(soup)
        agenda = next(
            (blocks[t] for t in ("revised agenda", "agenda") if t in blocks), None
        )
        # Only a bare "Minutes" block holds this meeting's minutes. "Minutes for
        # Adoption", "Minutes to be Adopted" and "Minutes to Adopt" are the
        # previous meeting's minutes, tabled here for ratification.
        return agenda, blocks.get("minutes")

    def _date_and_time(
        self, soup: BeautifulSoup, title: str
    ) -> tuple[str | None, str | None]:
        """Start date and time, preferring the add-to-calendar value.

        The page's visible time is only rendered for upcoming meetings, and a
        regex over the whole page text picks up PDF file sizes ("36.67 MB")
        ahead of any real time — so the ``<var>`` is the only sound source.
        """
        date = time = None

        var = soup.select_one("var.atc_date_start")
        if var:
            m = self._ATC_RE.search(var.get_text(" ", strip=True))
            if m:
                month, day, year, time = (
                    int(m.group(1)),
                    int(m.group(2)),
                    int(m.group(3)),
                    m.group(4).strip(),
                )
                try:
                    date = f"{datetime(year, month, day):%Y-%m-%d}"
                except ValueError:
                    date = None

        return date or self._date_from_title(title), time

    def _date_from_title(self, title: str) -> str | None:
        m = self._TITLE_DATE_RE.search(title or "")
        if not m:
            return None
        try:
            dt = datetime.strptime(
                f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y"
            )
        except ValueError:
            return None
        return f"{dt:%Y-%m-%d}"

    def _location(self, soup: BeautifulSoup) -> str:
        """Venue and street address, e.g. "Council Chamber, 8 Inglesby Road, Camberwell"."""
        parts = []
        for selector in (
            ".field--name-event-location",
            ".location-address span.address",
        ):
            el = soup.select_one(selector)
            if el:
                text = el.get_text(" ", strip=True)
                if text and text not in parts:
                    parts.append(text)
        return ", ".join(parts) if parts else self.default_location

    # ---------------------------------------------------------------- scraping

    def scraper(self) -> list[ScraperReturn]:
        years = self._years_filter()

        event_urls: list[str] = []
        for listing_url, newest_first in (
            (PAST_MEETINGS_URL, True),
            (UPCOMING_MEETINGS_URL, False),
        ):
            for url in self._listing_event_urls(listing_url, newest_first):
                if url not in event_urls:
                    event_urls.append(url)

        results: list[ScraperReturn] = []
        for event_url in event_urls:
            slug_year = self._year_from_slug(event_url)
            if years and slug_year and slug_year not in years:
                continue

            soup = self._soup(event_url)
            agenda_url, minutes_url = self._agenda_and_minutes(soup)
            if not agenda_url and not minutes_url:
                # Scheduled but nothing published yet, or a cancelled meeting.
                # A record with no documents fails the pipeline's required-field
                # check, so there is nothing to emit.
                continue

            h1 = soup.find("h1")
            name = h1.get_text(" ", strip=True) if h1 else "Council Meeting"
            date, time = self._date_and_time(soup, name)

            results.append(
                ScraperReturn(
                    name=name,
                    date=date,
                    time=time,
                    webpage_url=event_url,
                    download_url=agenda_url or minutes_url,  # backward compatibility
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    location=self._location(soup),
                )
            )

        return results
