from __future__ import annotations

import re
import html
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper

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
            council_name="strathfield", state="nsw", base_url=_STRATHFIELD_BASE_URL
        )

    def _fetch_index_html(self) -> str:
        """
        Strathfield blocks requests to /Council/Council-Meetings (403), so use selenium.
        """
        if not hasattr(self.fetcher, "fetch_with_selenium"):
            raise RuntimeError(
                "Strathfield requires selenium fetcher for the index page (requests returns 403)."
            )
        return self.fetcher.fetch_with_selenium(_STRATHFIELD_INDEX_URL)

    def _extract_latest_meeting_stub(self, index_html: str) -> _MeetingStub:
        """
        Pull the first meeting’s cvid/date/type from the index HTML.
        """
        cvid_match = _CVID_RE.search(index_html)
        if not cvid_match:
            raise ValueError("Could not find any data-cvid in index HTML")

        date_match = _DATE_RE.search(index_html)
        type_match = _TYPE_RE.search(index_html)

        if not date_match or not type_match:
            raise ValueError("Could not find meeting date/type in index HTML")

        return _MeetingStub(
            cvid=cvid_match.group(1).strip(),
            date=date_match.group(1).strip(),
            meeting_type=type_match.group(1).strip(),
        )

    def _cachebuster(self) -> str:
        return "1970-01-01T00:00:00.000Z"

    def _fetch_meeting_details_html(self, cvid: str) -> str:
        """
        Calls the same endpoint your browser calls when expanding an accordion row.

        NOTE: Strathfield also blocks direct requests to this endpoint (403),
        so fall back to selenium which has the right browser context/cookies.
        """
        params = {
            "url": _OC_DOCUMENTRENDERER_URL,
            "keywords": "",
            "cvid": cvid,
            "cachebuster": self._cachebuster(),
        }

        # Build the exact URL (useful for selenium fallback)
        details_url = f"{_OC_SERVICE_HANDLER_URL}?{urlencode(params)}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-AU,en;q=0.9",
            "Referer": _STRATHFIELD_INDEX_URL,
            "Origin": _STRATHFIELD_BASE_URL,
        }

        # 1) Try requests (fast)
        try:
            r = requests.get(
                _OC_SERVICE_HANDLER_URL, params=params, headers=headers, timeout=30
            )
            r.raise_for_status()
            return r.text
        except requests.exceptions.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            if status != 403:
                raise
            self.logger.warning(
                f"403 from requests for OCServiceHandler; falling back to selenium: {details_url}"
            )

        # 2) Selenium fallback (reliable)
        if not hasattr(self.fetcher, "fetch_with_selenium"):
            raise RuntimeError(
                "OCServiceHandler blocked (403) and no selenium fetcher available"
            )

        return self.fetcher.fetch_with_selenium(details_url)

    def _extract_agenda_url_from_details(self, details_html: str) -> str:
        """
        OpenCities documentrenderer may return:
        - HTML fragment
        - JSON containing an HTML fragment (escaped)
        - Something else with embedded PDF URLs

        Be robust:
        - try JSON decode
        - extract embedded HTML/text
        - search for agenda PDF links
        """
        payload_texts: list[str] = [details_html]

        # 1) If it's JSON, harvest all string fields (some responses are {"html":"..."} or {"d":"..."} etc)
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
                # Not valid JSON; ignore
                pass

        # 2) Normalise / unescape common encodings
        normalised_blobs: list[str] = []
        for t in payload_texts:
            # Unescape JSON-style escaped slashes and unicode escapes often seen in these payloads
            # (If it isn't escaped, these are harmless.)
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

        # 4) Regex fallback: find any PDF URLs in the raw content
        if not pdf_links:
            pdf_links = [m.group(0) for m in _PDF_URL_RE.finditer(combined)]

        if not pdf_links:
            raise ValueError(
                "Could not find any PDF links in OpenCities details response."
            )

        # 5) Prefer agenda-looking PDFs
        def score(u: str) -> int:
            lu = u.lower()
            s = 0
            if "agenda" in lu:
                s += 100
            if "business" in lu or "papers" in lu:
                s += 10
            if "minutes" in lu:
                s -= 50
            return s

        pdf_links = sorted(set(pdf_links), key=score, reverse=True)

        best = pdf_links[0]
        return urljoin(_STRATHFIELD_BASE_URL, best)

    def scraper(self) -> ScraperReturn:
        self.logger.info(
            f"Starting {self.council_name} scraper (OpenCities Minutes & Agendas)"
        )

        index_html = self._fetch_index_html()
        meeting = self._extract_latest_meeting_stub(index_html)
        self.logger.info(
            f"Latest meeting (from index): {meeting.name} (cvid={meeting.cvid})"
        )

        details_html = self._fetch_meeting_details_html(meeting.cvid)
        agenda_url = self._extract_agenda_url_from_details(details_html)

        self.logger.info(f"Found agenda: {agenda_url}")

        # time isn't reliably included in this flow; keep None
        return ScraperReturn(
            meeting.name, meeting.date, None, _STRATHFIELD_INDEX_URL, agenda_url
        )
