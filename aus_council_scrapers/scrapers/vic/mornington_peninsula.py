"""Mornington Peninsula Shire — OpenCities, same platform as Banyule.

Two differences from `banyule.py` are worth knowing before editing this:

* **No browser.** Banyule drives the year filter through Selenium because its
  filter is a JavaScript postback. Mornington Peninsula's pager is a plain
  ``<input type="submit">`` in ``form#mainForm``, so the whole scrape runs on
  ``fetch_with_requests`` — cheaper, and it does not depend on a Chrome the
  production runner never declared (see AGENTS.md).

* **Unstructured documents.** Banyule's meeting payload groups documents under
  ``<h3>Agenda</h3>`` / ``<h3>Minutes</h3>`` headings. Here every file for a
  meeting — agenda, minutes, attachment book, public notices, public question
  time, item attachments, community flyers — is one flat "Related Information"
  list, so the agenda and minutes have to be picked out by their link text.

**What this costs.** One listing request per page (16 as of September 2026)
plus one detail request per meeting (153), so ~170 requests, and at the default
2s ``FETCH_DELAY`` that is a little under six minutes in its own worker lane.
That is the largest per-council cost in the project and it is not avoidable:
the listing carries no document links at all, so the documents can only be
reached one meeting at a time. ``years_filter`` bounds the expensive half — see
`_wanted_years`.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.mornpen.vic.gov.au"

# The canonical listing URL, deliberately not the /About-Us/... alias recorded
# in docs/councils.md. That alias answers 302, and `requests` downgrades a
# redirected POST to a GET — which silently discards the pager's form data and
# hands back page 1 every time. The council then looks like one that publishes
# only ten meetings, with nothing to suggest the pager was the problem.
_LISTING_URL = (
    f"{_BASE_URL}"
    "/The-Shire/About-our-Council/Council-meetings"
    "/Council-Committee-meeting-agendas-and-minutes"
)

# ASP.NET control names for the listing's non-JavaScript pager. Selecting a
# page number and clicking "Go" is used rather than "Next": each request is
# then independent of the last, built from page 1's form state. "Next" reads
# the page number out of the state posted to it, so replaying it from a stale
# state returns the same page forever.
_PAGE_SELECT = "ctl10$ctl00$ctl08"
_GO_BUTTON = "ctl10$ctl00$ctl09"

# The pager's wrapper carries the page count as a class, e.g.
# `seamless-pagination seamless-pagination-count-16`.
_PAGE_COUNT_CLASS = re.compile(r"^seamless-pagination-count-(\d+)$")

# Meeting documents come from the OpenCities AJAX endpoint, keyed by the cvid
# on the listing row. No cachebuster, so each URL is unique per meeting and
# records/replays cleanly.
_OCSVC_URL = (
    f"{_BASE_URL}"
    "/OCServiceHandler.axd"
    "?url=ocsvc/Public/meetings/documentrenderer"
    "&keywords="
    "&cvid={cvid}"
)

_AGENDA = re.compile(r"\bagendas?\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)

# A revision of a paper rather than the paper itself. These are real documents
# and are used when nothing plainer exists, but a meeting holding both an
# "Agenda" and an "Addendum Agenda" should report the former.
_VARIANT = re.compile(
    r"\b(?:addendum|supplementary|errata|amended|revised)\b", re.IGNORECASE
)

_YEAR = re.compile(r"\b(\d{4})\b")


def _year_of(date_str: str) -> int | None:
    match = _YEAR.search(date_str)
    return int(match.group(1)) if match else None


def _form_state(html: str) -> dict[str, str]:
    """The fields ``form#mainForm`` would submit, as currently rendered.

    Submit buttons are left out so the caller adds exactly the one it wants to
    press. ``__SEAMLESSVIEWSTATE`` matters and is picked up here — the pager
    ignores a post that omits it — and unlike a classic ASP.NET
    ``__VIEWSTATE`` it is a couple of hundred bytes, so carrying it in the
    cassette key costs nothing.
    """
    soup = BeautifulSoup(html, "html.parser")
    state: dict[str, str] = {}

    for field in soup.find_all("input"):
        name = field.get("name")
        kind = (field.get("type") or "text").lower()
        if not name or kind in ("submit", "button", "image"):
            continue
        if kind in ("checkbox", "radio") and not field.get("checked"):
            continue
        state[name] = field.get("value", "")

    for select in soup.find_all("select"):
        name = select.get("name")
        if not name:
            continue
        chosen = select.find("option", selected=True) or select.find("option")
        state[name] = (chosen.get("value") if chosen else "") or ""

    return state


def _page_count(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup.find_all(class_=_PAGE_COUNT_CLASS):
        for class_name in element.get("class", []):
            match = _PAGE_COUNT_CLASS.match(class_name)
            if match:
                return int(match.group(1))
    # No pager at all is what a single page of results looks like.
    return 1


def _parse_listing_items(html: str) -> list[tuple[str, str, str]]:
    """Return ``(date, meeting_type, cvid)`` for each row on a listing page."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for container in soup.find_all("div", class_="accordion-list-item-container"):
        trigger = container.find("a", class_="accordion-trigger")
        if not trigger:
            continue
        cvid = trigger.get("data-cvid", "").strip()
        date_span = container.find("span", class_="minutes-date")
        type_span = container.find("span", class_="meeting-type")
        date_str = date_span.get_text(strip=True) if date_span else ""
        meeting_type = type_span.get_text(strip=True) if type_span else ""
        if cvid and date_str:
            items.append((date_str, meeting_type, cvid))
    return items


def _papers(content: BeautifulSoup) -> dict[str, str]:
    """Pick the agenda and minutes out of a meeting's document list.

    Classification is on the **link text only**, never the href: every file
    lives under ``/files/assets/.../meetings-amp-minutes/...``, so matching the
    URL scores "minutes" against every attachment book the shire publishes.

    Everything else in the list is left alone. It is a long tail — attachment
    books, public notices of cancelled and rescheduled meetings, public
    question time responses, individual item attachments, community meeting
    flyers — and none of it is the agenda or the minutes.
    """
    candidates = []
    for anchor in content.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href.lower().split("?")[0].endswith(".pdf"):
            # Skips the livestream links and the "Download All" zip.
            continue
        candidates.append((anchor.get_text(" ", strip=True), href))

    papers: dict[str, str] = {}
    # Plainly named papers first, so an addendum only fills a gap.
    for variants in (False, True):
        for text, href in candidates:
            if bool(_VARIANT.search(text)) is not variants:
                continue
            if _AGENDA.search(text):
                papers.setdefault("agenda", urljoin(_BASE_URL, href))
            elif _MINUTES.search(text):
                papers.setdefault("minutes", urljoin(_BASE_URL, href))

    # One file cannot be both. The shire occasionally lists the same PDF twice
    # under two labels — the Cemetery Trust's 21 August 2024 agenda is offered
    # again as that meeting's minutes — and reporting it as minutes would
    # manufacture a document that was never published. The agenda is kept
    # because that is what the file is named.
    if papers.get("minutes") == papers.get("agenda"):
        papers.pop("minutes", None)

    return papers


@register_scraper
class MorningtonPeninsulaScraper(BaseScraper):
    def __init__(self):
        council = "mornington_peninsula"
        state = "VIC"
        self.webpage_url = _LISTING_URL
        super().__init__(council, state, _BASE_URL)

    # ------------------------------------------------------------------
    # Step 1: every meeting on the listing
    # ------------------------------------------------------------------

    def _listing_pages(self):
        """Yield the HTML of each page of the unfiltered listing.

        The listing has its own year filter, which is not used: unfiltered it
        already reaches back to the shire's earliest published meeting
        (February 2022), so filtering by year would cost the same requests to
        return a subset. It also offers 2018, which holds nothing at all.
        """
        first = self.fetcher.fetch_with_requests(_LISTING_URL)
        yield first

        state = _form_state(first)
        for page in range(2, _page_count(first) + 1):
            data = {**state, _PAGE_SELECT: str(page), _GO_BUTTON: "Go"}
            try:
                yield self.fetcher.fetch_with_requests(
                    _LISTING_URL, method="POST", data=data
                )
            except Exception:
                # One unreachable page costs ten meetings; abandoning the run
                # costs all of them.
                self.logger.exception(f"Listing page {page} failed; skipping it.")

    def _wanted_years(self) -> set[int] | None:
        """The years to fetch details for, or None for no restriction.

        Worth honouring here more than in most scrapers: the detail fetches
        are ~90% of this scraper's runtime, so a `--years 2025` run drops from
        around six minutes to under one.
        """
        years = getattr(self, "years_filter", None)
        return {int(year) for year in years} if years else None

    def _meeting_index(self) -> list[tuple[str, str, str]]:
        wanted = self._wanted_years()
        items: list[tuple[str, str, str]] = []
        seen: set[str] = set()

        for html in self._listing_pages():
            for date_str, meeting_type, cvid in _parse_listing_items(html):
                if cvid in seen:
                    continue
                seen.add(cvid)
                year = _year_of(date_str)
                if year is None or year < EARLIEST_YEAR:
                    continue
                if wanted is not None and year not in wanted:
                    continue
                items.append((date_str, meeting_type, cvid))

        return items

    # ------------------------------------------------------------------
    # Step 2: one meeting's documents
    # ------------------------------------------------------------------

    def _fetch_meeting(self, cvid: str) -> BeautifulSoup | None:
        try:
            raw = self.fetcher.fetch_with_requests(_OCSVC_URL.format(cvid=cvid))
        except Exception as e:
            self.logger.warning(f"Error fetching meeting {cvid}: {e}")
            return None

        try:
            html = json.loads(raw).get("html", "")
        except json.JSONDecodeError:
            self.logger.warning(f"Could not parse meeting JSON for {cvid}")
            return None

        return BeautifulSoup(html, "html.parser") if html else None

    def _build_scraper_return(
        self, content: BeautifulSoup, date_str: str, meeting_type: str
    ) -> ScraperReturn | None:
        papers = _papers(content)
        agenda_url = papers.get("agenda")
        minutes_url = papers.get("minutes")
        if not agenda_url and not minutes_url:
            # A meeting that was cancelled or rescheduled keeps its listing row
            # and publishes only a notice saying so. There is no meeting here
            # to report.
            return None

        time_value = None
        time_div = content.find("div", class_="meeting-time")
        if time_div:
            # "Time 06:30 PM", or "Time 01:00 PM - 02:00 PM" for the Cemetery
            # Trust, whose rows carry a finish time as well. The regex takes
            # the start.
            raw_time = re.sub(
                r"^\s*Time\b", "", time_div.get_text(" ", strip=True)
            ).strip()
            match = self.time_regex.search(raw_time)
            time_value = match.group() if match else None

        # Location is deliberately not set. Unlike Banyule, these payloads have
        # no `meeting-address` element — not one of the 153 meetings recorded
        # in September 2026 — and the address appears only inside free prose
        # that also carries rescheduling notices and livestream instructions
        # ("Meeting reschduled from the 4 August 2026. Meeting was held at
        # 6.30pm at the Municipal Offices..."). Storing a slice of that as the
        # location would be inventing a field, so it stays empty.
        return ScraperReturn(
            name=meeting_type or self.default_name,
            date=date_str,
            time=time_value,
            webpage_url=self.webpage_url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        items = self._meeting_index()
        self.logger.info(f"Found {len(items)} meeting entries to process")

        results: list[ScraperReturn] = []
        for date_str, meeting_type, cvid in items:
            content = self._fetch_meeting(cvid)
            if content is None:
                continue
            record = self._build_scraper_return(content, date_str, meeting_type)
            if record:
                results.append(record)

        if not results:
            self.logger.warning(f"No meetings found for {self.council_name}")
        else:
            self.logger.info(f"Found {len(results)} {self.council_name} meetings")

        return results
