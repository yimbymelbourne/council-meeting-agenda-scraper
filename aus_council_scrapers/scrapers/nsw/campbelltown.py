from __future__ import annotations

import datetime
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper


_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"

# Matches "14 May" (year appended later) or "14 May 2026"
_DATE_RE = re.compile(rf"(\d{{1,2}}\s+({_MONTHS})(?:\s+\d{{4}})?)", re.IGNORECASE)


@register_scraper
class CampbelltownScraper(BaseScraper):
    def __init__(self):
        council = "campbelltown"
        state = "NSW"
        base_url = "https://www.campbelltown.nsw.gov.au"
        super().__init__(council, state, base_url)
        self.default_location = (
            "Corner Queen and Broughton Streets, Campbelltown NSW 2560"
        )

    def _fetch_html(self, url: str) -> str:
        """
        Requests first; if blocked (403), fall back to selenium
        """
        try:
            return self.fetcher.fetch_with_requests(url)
        except Exception as e:
            # Generic so it still works with PlaybackFetcher behaviour.
            if "403" not in str(e):
                raise
            if not hasattr(self.fetcher, "fetch_with_selenium"):
                raise
            self.logger.warning(
                f"403 fetching {url} with requests; falling back to selenium"
            )
            return self.fetcher.fetch_with_selenium(url)

    def _get_latest_business_papers_url(self, meetings_url: str) -> tuple[int, str]:
        """
        Prefer parsing the Meetings-and-Minutes page to discover the newest year.
        In test playback mode, that URL may not exist in replay data; fall back to a
        deterministic set of year pages.
        """
        try:
            html = self._fetch_html(meetings_url)
            soup = BeautifulSoup(html, "html.parser")

            candidates: list[tuple[int, str]] = []
            for a in soup.select("a[href]"):
                href = a.get("href") or ""
                m = re.search(r"/(\d{4})-Business-Papers\b", href)
                if not m:
                    continue
                year = int(m.group(1))
                candidates.append((year, urljoin(self.base_url, href)))

            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                return candidates[0]
        except KeyError:
            self.logger.info(
                "Replay data missing Meetings-and-Minutes URL; falling back to year guesses."
            )
        except Exception:
            self.logger.info(
                "Could not derive Business Papers year from Meetings-and-Minutes; falling back."
            )

        this_year = datetime.date.today().year
        for year in [this_year, this_year - 1, this_year - 2]:
            candidate = urljoin(
                self.base_url,
                f"/Council-and-Councillors/Meetings-and-Minutes/{year}-Business-Papers#section-1",
            )
            try:
                _ = self._fetch_html(candidate)
                return year, candidate
            except Exception:
                continue

        raise RuntimeError(
            "Could not find a working Business Papers page from fallbacks."
        )

    def _find_latest_meeting_header(self, soup: BeautifulSoup):
        # Prefer an h2 that clearly indicates a meeting section
        for h2 in soup.find_all("h2"):
            txt = (h2.get_text(" ", strip=True) or "").lower()
            if "meeting" in txt:
                return h2
        return soup.find("h2")

    def _find_agenda_link_within_section(self, header) -> str | None:
        """
        Scan from this header until the next <h2>, pick the first PDF link that looks like an agenda.
        """
        node = header
        while True:
            node = node.find_next_sibling()
            if node is None:
                return None
            if getattr(node, "name", None) == "h2":
                return None

            for a in node.select("a[href]"):
                href = (a.get("href") or "").strip()
                if not href or ".pdf" not in href.lower():
                    continue
                txt = (a.get_text(" ", strip=True) or "").lower()
                if "agenda" in txt and "minute" not in txt:
                    return urljoin(self.base_url, href)

        # unreachable

    def _find_minutes_link_within_section(self, header) -> str | None:
        """
        Scan from this header until the next <h2>, pick the first PDF link that looks like minutes.
        """
        node = header
        while True:
            node = node.find_next_sibling()
            if node is None:
                return None
            if getattr(node, "name", None) == "h2":
                return None

            for a in node.select("a[href]"):
                href = (a.get("href") or "").strip()
                if not href or ".pdf" not in href.lower():
                    continue
                txt = (a.get_text(" ", strip=True) or "").lower()
                if "minute" in txt:
                    return urljoin(self.base_url, href)

        # unreachable

    def scraper(self) -> ScraperReturn:
        self.logger.info(f"Starting {self.council_name} scraper")

        meetings_url = urljoin(
            self.base_url, "/Council-and-Councillors/Meetings-and-Minutes"
        )
        papers_year, webpage_url = self._get_latest_business_papers_url(meetings_url)

        output = self._fetch_html(webpage_url)
        soup = BeautifulSoup(output, "html.parser")

        header = self._find_latest_meeting_header(soup)
        if not header:
            raise ValueError(
                "Could not find meeting header <h2> on Business Papers page"
            )

        header_text = header.get_text(" ", strip=True)

        # Date: prefer extracting from header; if it includes no year, append papers_year
        date_match = _DATE_RE.search(header_text)
        if date_match:
            date_raw = date_match.group(1)
            # if year already present, keep it; otherwise append papers_year
            if re.search(r"\b\d{4}\b", date_raw):
                date = date_raw
            else:
                date = f"{date_raw} {papers_year}"
        else:
            # fallback: still parseable, but clearly a fallback
            date = f"1 January {papers_year}"

        # Name: keep stable “meeting type” (fixture-friendly)
        # e.g. "Ordinary Meeting 14 May" -> "Ordinary Meeting"
        name = header_text
        if date_match:
            name = (
                header_text[: date_match.start()].strip(" -\u2013\u2014") or header_text
            )

        # Agenda link: prefer within the first meeting section
        download_url = self._find_agenda_link_within_section(header)

        # Fallback: any agenda-looking pdf link on page
        if not download_url:
            for a in soup.select("a[href]"):
                href = (a.get("href") or "").strip()
                if not href or ".pdf" not in href.lower():
                    continue
                txt = (a.get_text(" ", strip=True) or "").lower()
                if "agenda" in txt and "minute" not in txt:
                    download_url = urljoin(self.base_url, href)
                    break

        # Last fallback: first pdf link after header
        if not download_url:
            a = header.find_next("a", href=True)
            if not a:
                raise ValueError("Could not find any PDF links for the latest meeting")
            download_url = urljoin(self.base_url, a["href"])

        # Minutes link: look within the same section
        minutes_url = self._find_minutes_link_within_section(header)

        # Time: not provided on page
        time = None

        return ScraperReturn(
            name=name,
            date=date,
            time=time,
            webpage_url=webpage_url,
            agenda_url=download_url,
            minutes_url=minutes_url,
            download_url=download_url,  # For backward compatibility
            location=self.default_location,
        )
