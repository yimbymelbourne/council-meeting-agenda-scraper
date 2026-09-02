from __future__ import annotations

import re
import html
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

from urllib.parse import urlencode

_STRATHFIELD_BASE_URL = "https://www.strathfield.nsw.gov.au"
_STRATHFIELD_INDEX_URL = urljoin(_STRATHFIELD_BASE_URL, "/Council/Council-Meetings")

# OpenCities XHR endpoint (from DevTools)
_OC_SERVICE_HANDLER_URL = urljoin(_STRATHFIELD_BASE_URL, "/OCServiceHandler.axd")
_OC_DOCUMENTRENDERER_URL = "ocsvc/Public/meetings/documentrenderer"

# Meeting list on the index page is an accordion with AJAX triggers and no href.
# The HTML contains e.g.:
# <a class="accordion-trigger minutes-trigger ajax-trigger" data-cvid="...">
_CVID_RE = re.compile(r'data-cvid="([^"]+)"', re.IGNORECASE)

# These spans appear in the same accordion item:
# <span class="minutes-date">16 December 2025</span>
# <span class="meeting-type">Extraordinary Meeting</span>
_DATE_RE = re.compile(
    r'<span class="minutes-date">\s*([^<]+?)\s*</span>', re.IGNORECASE
)
_TYPE_RE = re.compile(
    r'<span class="meeting-type">\s*([^<]+?)\s*</span>', re.IGNORECASE
)

# In the rendered HTML snippet, anchors include "Agenda" in text.
_AGENDA_TEXT_RE = re.compile(r"\bagenda\b", re.IGNORECASE)

_PDF_URL_RE = re.compile(
    r'(https?://[^"\s]+\.pdf[^"\s]*|/[^"\s]+\.pdf[^"\s]*)', re.IGNORECASE
)


@dataclass(frozen=True)
class _MeetingStub:
    cvid: str
    date: str
    meeting_type: str

    @property
    def name(self) -> str:
        return f"{self.date} {self.meeting_type}".strip()


@register_scraper
class StrathfieldNSWScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            council_name="strathfield", state="NSW", base_url=_STRATHFIELD_BASE_URL
        )

    def _fetch_index_html(self, page: int = 1) -> str:
        """
        Strathfield blocks requests to /Council/Council-Meetings (403), so use selenium.
        Page numbering starts at 1 for the first page, and uses ?dlv_OC%20CL%20Public%20Meetings=(pageindex=N) for others.
        """
        if not hasattr(self.fetcher, "fetch_with_selenium"):
            raise RuntimeError(
                "Strathfield requires selenium fetcher for the index page (requests returns 403)."
            )

        if page == 1:
            url = _STRATHFIELD_INDEX_URL
        else:
            url = f"{_STRATHFIELD_INDEX_URL}?dlv_OC%20CL%20Public%20Meetings=(pageindex={page})"

        return self.fetcher.fetch_with_selenium(url)

    def _extract_meeting_stubs(self, index_html: str) -> list[_MeetingStub]:
        """
        Extract all meetings from a page of the index HTML.
        Returns a list of _MeetingStub objects.
        """
        stubs = []

        # Find all data-cvid attributes
        cvid_matches = list(_CVID_RE.finditer(index_html))
        if not cvid_matches:
            return stubs

        # For each cvid, find the corresponding date and type
        # We need to search for date/type patterns near each cvid
        for cvid_match in cvid_matches:
            cvid = cvid_match.group(1).strip()

            # Search for date and type after the cvid position
            pos = cvid_match.end()
            remaining_html = index_html[pos:]

            # Look ahead up to 1000 characters for the date/type (should be nearby)
            search_window = remaining_html[:1000]

            date_match = _DATE_RE.search(search_window)
            type_match = _TYPE_RE.search(search_window)

            if date_match and type_match:
                stubs.append(
                    _MeetingStub(
                        cvid=cvid,
                        date=date_match.group(1).strip(),
                        meeting_type=type_match.group(1).strip(),
                    )
                )

        return stubs

    def _cachebuster(self) -> str:
        return "1970-01-01T00:00:00.000Z"

    def _fetch_meeting_details_html(self, cvid: str) -> str:
        """
        Calls the same endpoint your browser calls when expanding an accordion row.

        Strathfield blocks requests to this endpoint (403), so always use selenium.
        """
        params = {
            "url": _OC_DOCUMENTRENDERER_URL,
            "keywords": "",
            "cvid": cvid,
            "cachebuster": self._cachebuster(),
        }

        details_url = f"{_OC_SERVICE_HANDLER_URL}?{urlencode(params)}"
        return self.fetcher.fetch_with_selenium(details_url)

    def _extract_urls_from_details(
        self, details_html: str
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Parse the OpenCities documentrenderer response and return (agenda_url, minutes_url).
        Either may be None if not found.
        """
        payload_texts: list[str] = [details_html]

        # 1) If it's JSON, harvest all string fields
        stripped = details_html.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                obj = json.loads(details_html)

                def collect_strings(x):
                    if isinstance(x, str):
                        payload_texts.append(x)
                    elif isinstance(x, dict):
                        for v in x.values():
                            collect_strings(v)
                    elif isinstance(x, list):
                        for v in x:
                            collect_strings(v)

                collect_strings(obj)
            except Exception:
                pass

        # 2) Normalise / unescape common encodings
        normalised_blobs: list[str] = []
        for t in payload_texts:
            t2 = t.replace("\\/", "/")
            try:
                t2 = bytes(t2, "utf-8").decode("unicode_escape")
            except Exception:
                pass
            t2 = html.unescape(t2)
            normalised_blobs.append(t2)

        combined = "\n".join(normalised_blobs)

        # 3) Try to parse anchors if there's HTML
        soup = BeautifulSoup(combined, "html.parser")
        pdf_links: list[str] = []

        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            if ".pdf" in href.lower():
                pdf_links.append(href)

        # 4) Regex fallback
        if not pdf_links:
            pdf_links = [m.group(0) for m in _PDF_URL_RE.finditer(combined)]

        # A meeting with no documents is a real meeting, not a failure. Strathfield
        # answers `status: Okay` with nothing but a meeting-time block for two 2020
        # meetings it never published papers for. Raising here dropped them from the
        # output entirely, which understated the council's meeting count to hide two
        # missing PDFs.
        if not pdf_links:
            return None, None

        pdf_links = list(dict.fromkeys(pdf_links))  # deduplicate, preserve order

        # 5) Classify each link
        agenda_url: Optional[str] = None
        minutes_url: Optional[str] = None

        for href in pdf_links:
            lu = href.lower()
            absolute = urljoin(_STRATHFIELD_BASE_URL, href)
            if "agenda" in lu or "business" in lu or "papers" in lu:
                if agenda_url is None:
                    agenda_url = absolute
            elif "minutes" in lu:
                if minutes_url is None:
                    minutes_url = absolute

        # Fallback: if nothing was classified, treat the first link as the agenda
        if agenda_url is None and minutes_url is None and pdf_links:
            agenda_url = urljoin(_STRATHFIELD_BASE_URL, pdf_links[0])

        return agenda_url, minutes_url

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(
            f"Starting {self.council_name} scraper (OpenCities Minutes & Agendas)"
        )

        years_filter: set[int] | None = getattr(self, "years_filter", None)
        if years_filter:
            years_filter = set(years_filter)
            min_year = min(years_filter)
        else:
            min_year = EARLIEST_YEAR

        all_results = []
        page = 1
        should_continue = True

        while should_continue:
            self.logger.info(f"Fetching page {page}")

            # Deliberately unguarded. A failed page fetch is not the end of the
            # listing, and treating it as one truncated the run and reported the
            # truncation as success: the 2026-09-01 production run returned page
            # one's ten meetings for 2026 and logged "10 meetings" when the year
            # holds fifteen. An empty page below is the only legitimate end of
            # pagination; anything else must go red.
            index_html = self._fetch_index_html(page)
            meetings = self._extract_meeting_stubs(index_html)

            if not meetings:
                self.logger.info(
                    f"No meetings found on page {page}, stopping pagination"
                )
                break

            self.logger.info(f"Found {len(meetings)} meetings on page {page}")

            for meeting in meetings:
                try:
                    meeting_date = datetime.strptime(meeting.date, "%d %B %Y")
                    meeting_year = meeting_date.year
                except ValueError:
                    self.logger.warning(f"Could not parse date: {meeting.date}")
                    meeting_year = None

                if meeting_year is not None and meeting_year < min_year:
                    self.logger.info(
                        f"Meeting {meeting.name} is before {min_year}, stopping pagination"
                    )
                    should_continue = False
                    break

                # Skip meetings outside the requested years
                if years_filter and meeting_year not in years_filter:
                    continue

                # Also unguarded, for the same reason: a meeting we cannot fetch
                # details for is a meeting missing from the output, and dropping
                # it quietly makes a short run indistinguishable from a full one.
                # A meeting that simply has no documents is handled in
                # `_extract_urls_from_details`, and is not an error.
                details_html = self._fetch_meeting_details_html(meeting.cvid)
                agenda_url, minutes_url = self._extract_urls_from_details(details_html)

                if agenda_url:
                    self.logger.info(f"Found agenda for {meeting.name}: {agenda_url}")
                if minutes_url:
                    self.logger.info(f"Found minutes for {meeting.name}: {minutes_url}")

                # Strathfield publishes two 2020 meetings with no papers at all —
                # `status: Okay`, nothing but a meeting-time block. Those are real
                # meetings, but downstream keys a meeting on its document URL, so a
                # row with no documents has no identity and `ingestCouncils` drops it
                # on arrival ("the scrapers shouldn't emit these"). Skip it here,
                # where it is visible and named, rather than emitting something that
                # cannot be stored. This is not the same as a failure, which raises.
                if not agenda_url and not minutes_url:
                    self.logger.info(
                        f"No documents published for {meeting.name}, skipping"
                    )
                    continue

                all_results.append(
                    ScraperReturn(
                        name=meeting.name,
                        date=meeting.date,
                        time=None,
                        webpage_url=_STRATHFIELD_INDEX_URL,
                        download_url=agenda_url,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                    )
                )

            page += 1

        self.logger.info(f"Scraped {len(all_results)} meetings total")
        return all_results
