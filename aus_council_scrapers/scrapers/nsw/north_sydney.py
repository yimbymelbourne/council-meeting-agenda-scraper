from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.northsydney.nsw.gov.au"
_LISTING_URL = f"{_BASE_URL}/council-meetings"

# Listing entries link to a numbered meeting page, e.g.
# /council-meetings/304/24-08-2026-council-meeting. The sidebar of that page
# links documents under /ecm/download/, while the body links the individual
# reports that make up the business paper under /ecm/download-meeting-consent/.
# Only the former are the agenda and the minutes—except on some extraordinary
# meeting pages, whose sidebar is empty and whose agenda and minutes sit in the
# body instead (see `_documents`).
_MEETING_HREF = re.compile(r"^/council-meetings/\d+/")

# "24/08/2026           Council Meeting"—the site pads the anchor text.
_LISTING_TEXT = re.compile(r"^(\d{2}/\d{2}/\d{4})\s*(.*)$")

# Until 2023 the listing titled meetings "Council Reports" and "Extraordinary
# Council Reports"—the name of the page, not of the meeting. The agendas call
# them meetings of Council, as the listing has since 2024.
_REPORTS_SUFFIX = re.compile(r"\bReports$")

# Links filed under an "Agenda" or "Minutes" heading that are not that
# document. The 14 September 2026 agenda list leads with four "9.1 Addendum
# QWN" answers to questions with notice before the agenda itself, and a few
# older lists carry a stray "test" upload after the real one. "Attachment"
# counts only at the start: the 16 January 2023 agenda is labelled "Agenda
# Report and Attachment" and is the whole 95-page agenda.
_NOT_THE_DOCUMENT = re.compile(
    r"addend|supplementar|^attachment|\blate\b|\btest\b", re.IGNORECASE
)

# Published on the listing page: "Council meetings start at 7pm and are held
# in Council Chambers." That is true of ordinary meetings since the council
# elected in September 2024—from 28 October 2024 every agenda says 7.00pm.
# Before then they said 6.30pm (and 7.30pm in 2022), and extraordinary
# meetings set their own time (6pm on 30 June 2025, 11am on 1 July 2026). The
# meeting pages carry no time, so outside the case the council states, the
# time is left unset rather than guessed.
_ORDINARY_MEETING = "Council Meeting"
_SEVEN_PM_SINCE = datetime(2024, 10, 28)
_ORDINARY_TIME = "7:00pm"
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

    return date, _REPORTS_SUFFIX.sub("Meeting", match.group(2).strip())


def _meeting_time(date: datetime, name: str) -> str | None:
    if name == _ORDINARY_MEETING and date >= _SEVEN_PM_SINCE:
        return _ORDINARY_TIME
    return None


def _pick_document(links, label: str):
    """The link in a heading's list that is the agenda or minutes itself.

    Prefer one whose text starts with the label ("Agenda", "Minutes - 5 July
    2021"); failing that the first link that is not an addendum or test upload
    ("Summary Agenda 26 October 2026", "1 March agenda"). If every link is an
    addendum there is no agenda to report, so return None rather than store
    one in its place.
    """
    candidates = [
        link
        for link in links
        if not _NOT_THE_DOCUMENT.search(link.get_text(" ", strip=True))
    ]
    for link in candidates:
        if link.get_text(" ", strip=True).lower().startswith(label):
            return link
    return candidates[0] if candidates else None


@register_scraper
class NorthSydneyScraper(BaseScraper):
    # One production year, measured Oct 2026 from a home IP: 41 s
    # for 21 requests (was 272 s before it honoured years_filter).
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 41

    def __init__(self):
        council = "north_sydney"
        state = "NSW"
        super().__init__(council, state, _BASE_URL)
        self.default_location = _DEFAULT_LOCATION

    # ------------------------------------------------------------------
    # Step 1: walk the paginated listing
    # ------------------------------------------------------------------

    def _next_page_url(self, soup: BeautifulSoup) -> str | None:
        link = soup.select_one("li.pagination__item--next a.pagination__link")
        return urljoin(_BASE_URL, link["href"]) if link and link.get("href") else None

    def _wanted_years(self) -> set[int]:
        """The years whose meeting pages are worth fetching.

        A meeting page is one request each, and the unfiltered history is
        ~120 of them, so in production—which asks for a single year—
        ``years_filter`` is what keeps this scraper from spending four minutes
        fetching pages ``main.py`` then throws away.
        """
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _collect_meetings(self) -> list[tuple[datetime, str, str]]:
        """Return (date, name, meeting page URL) for every meeting worth fetching.

        The listing is one long run of meetings newest first—the site's own
        year filter is inert (``?year=2024`` returns the unfiltered first page),
        so pagination is the only way through it. Because the order is strictly
        descending, a page whose every entry predates the earliest wanted year
        means the rest of the archive does too, and there is nothing left to
        page to. Unfiltered that is ``EARLIEST_YEAR``, ~13 listing pages; for a
        single current year it is the first three or so.
        """
        wanted = self._wanted_years()
        earliest_wanted = min(wanted)

        meetings: list[tuple[datetime, str, str]] = []
        seen_urls: set[str] = set()
        url: str | None = _LISTING_URL

        while url and url not in seen_urls:
            seen_urls.add(url)
            soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

            entries = 0
            recent_enough = 0
            for anchor in soup.find_all("a", class_="listing__link", href=True):
                parsed = _parse_listing_entry(anchor)
                if not parsed:
                    continue
                entries += 1
                date, name = parsed
                if date.year >= earliest_wanted:
                    recent_enough += 1
                # The listing date is the meeting's own, so it decides whether
                # the page is fetched at all—not just whether it is kept.
                if date.year in wanted:
                    meetings.append((date, name, urljoin(_BASE_URL, anchor["href"])))

            if entries and not recent_enough:
                break

            url = self._next_page_url(soup)

        return meetings

    # ------------------------------------------------------------------
    # Step 2: read the agenda and minutes off each meeting page
    # ------------------------------------------------------------------

    def _documents(self, soup: BeautifulSoup) -> tuple[str | None, str | None]:
        """Return (agenda URL, minutes URL) from a meeting page.

        Normally they are in the sidebar: a run of ``<h2>Agenda 24 August
        2026</h2>`` followed by a list of links. The link text is unreliable—
        recent meetings label it "Agenda", older ones "Agenda - 28 June 2021"—
        so the heading above the list is what says which document it is, and
        `_pick_document` chooses among the links when the list holds more than
        the one.

        Some extraordinary meetings (21 January and 1 July 2026, 28 February
        and 1 March 2023, 5 July 2021) have an empty sidebar and put the agenda
        and minutes in the body's accordion instead, under "Agenda 01 July
        2026" and "Minutes 01 July 2026" tabs. Those links go through
        /ecm/download-meeting-consent/, which serves the PDF directly, the same
        bytes as /ecm/download/. Ordinary meeting pages use the accordion for
        "Reports to Council" and "Mayoral Minutes"—individual reports, not the
        agenda—so the accordion is read only when the sidebar has nothing.
        """
        sections: list[tuple[str, list]] = []

        for aside in soup.find_all("div", class_="aside--sidebar"):
            for heading in aside.find_all("h2"):
                # Skip the <h2 class="listing__heading"> wrapping each link.
                if heading.get("class"):
                    continue
                document_list = heading.find_next_sibling("ul")
                if not document_list:
                    continue
                sections.append(
                    (
                        heading.get_text(" ", strip=True).lower(),
                        document_list.find_all("a", class_="listing__link", href=True),
                    )
                )

        agenda_url, minutes_url = self._first_of_each(sections)
        if agenda_url or minutes_url:
            return agenda_url, minutes_url

        body_sections = []
        for item in soup.select("li.accordion__item"):
            heading = item.select_one("span.accordion__tab-heading")
            if heading:
                body_sections.append(
                    (
                        heading.get_text(" ", strip=True).lower(),
                        item.select("a.listing__link[href]"),
                    )
                )
        return self._first_of_each(body_sections)

    def _first_of_each(
        self, sections: list[tuple[str, list]]
    ) -> tuple[str | None, str | None]:
        agenda_url = minutes_url = None
        for label, links in sections:
            # "Mayoral Minutes 14 September 2026" does not start with
            # "minutes", so it is passed over here.
            for word in ("agenda", "minutes"):
                if not label.startswith(word):
                    continue
                link = _pick_document(links, word)
                if not link:
                    continue
                url = urljoin(_BASE_URL, link["href"])
                if word == "agenda" and not agenda_url:
                    agenda_url = url
                elif word == "minutes" and not minutes_url:
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
                    time=_meeting_time(date, name),
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
