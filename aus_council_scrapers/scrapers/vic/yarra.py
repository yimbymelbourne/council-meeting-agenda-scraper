import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper


@register_scraper
class YarraScraper(BaseScraper):
    def __init__(self):
        council = "yarra"
        state = "VIC"
        base_url = "https://www.yarracity.vic.gov.au"
        super().__init__(council, state, base_url)

    def _abs(self, href: str) -> str:
        return urljoin(self.base_url, href)

    def _parse_date_from_text(self, text: str):
        m = re.search(self.date_regex, text)
        if not m:
            return None
        try:
            return parse_date(m.group(), dayfirst=True).date()
        except Exception:
            return None

    def _parse_time_from_text(self, text: str) -> str | None:
        m = re.search(self.time_regex, text)
        if not m:
            return None
        return m.group().replace(".", ":")

    def _extract_meeting_links(
        self, index_soup: BeautifulSoup
    ) -> list[tuple[object, str, str]]:
        """
        Returns list of (meeting_date, meeting_text, meeting_url)
        Only includes /about-us/committees-meetings-and-minutes/council-meeting-... pages.
        """
        out: list[tuple[object, str, str]] = []
        for a in index_soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href:
                continue

            abs_href = self._abs(href)
            if (
                "/about-us/committees-meetings-and-minutes/council-meeting-"
                not in abs_href
            ):
                continue

            text = a.get_text(" ", strip=True)
            dt = self._parse_date_from_text(text)
            if not dt:
                continue

            out.append((dt, text, abs_href))

        # de-dupe by url, keep first occurrence
        seen = set()
        deduped = []
        for dt, text, url in out:
            if url in seen:
                continue
            seen.add(url)
            deduped.append((dt, text, url))
        return deduped

    def _find_agenda_in_documents_section(
        self, meeting_soup: BeautifulSoup
    ) -> str | None:
        """
        On Yarra meeting pages, the agenda is under a 'Documents' heading.
        Example: '## Documents' then links: Agenda / Minutes / Recording. :contentReference[oaicite:3]{index=3}
        """
        docs_h = meeting_soup.find(
            ["h2", "h3"], string=re.compile(r"^\s*Documents\s*$", re.I)
        )
        if not docs_h:
            return None

        # Usually the links appear right after the heading, within the same parent container.
        scope = docs_h.parent or meeting_soup
        # If the CMS puts them in the next sibling, include that too.
        scopes = [scope]
        sib = docs_h.find_next_sibling()
        if sib:
            scopes.append(sib)

        for sc in scopes:
            for a in sc.find_all("a", href=True):
                label = a.get_text(" ", strip=True).lower()
                if not label.startswith("agenda"):
                    continue
                href = a["href"].strip()
                if not href:
                    continue
                return self._abs(href)

        return None

    def _extract_location(self, meeting_soup: BeautifulSoup) -> str | None:
        # Best-effort: the "Where" section includes address lines like:
        # "201 Napier Street, Fitzroy 3065" :contentReference[oaicite:4]{index=4}
        text = meeting_soup.get_text("\n", strip=True)
        for line in text.splitlines():
            # crude but effective for AU addresses with postcode
            if re.search(r"\bVIC\b\s*\d{4}\b", line) or re.search(r"\b\d{4}\b", line):
                if "," in line and any(ch.isdigit() for ch in line):
                    return line.strip()
        return None

    def scraper(self) -> list[ScraperReturn]:
        index_url = "https://www.yarracity.vic.gov.au/about-us/council-and-committee-meetings/council-meetings"
        index_html = self.fetcher.fetch_with_requests(index_url)
        index_soup = BeautifulSoup(index_html, "html.parser")

        meetings = self._extract_meeting_links(index_soup)
        if not meetings:
            return []

        # Sort newest-first and only check the most recent N to keep it fast.
        # This still picks up future agendas once published because those meetings are near the top. :contentReference[oaicite:5]{index=5}
        meetings.sort(key=lambda x: x[0], reverse=True)
        meetings_to_check = meetings[:30]

        best = None  # (meeting_date, meeting_url, agenda_url, meeting_soup)
        for meeting_date, meeting_text, meeting_url in meetings_to_check:
            meeting_html = self.fetcher.fetch_with_requests(meeting_url)
            meeting_soup = BeautifulSoup(meeting_html, "html.parser")

            agenda_url = self._find_agenda_in_documents_section(meeting_soup)
            if not agenda_url:
                # Future meeting before agenda publish, or page missing docs section. :contentReference[oaicite:6]{index=6}
                continue

            # pick the latest dated meeting that actually has an agenda
            if best is None or meeting_date > best[0]:
                best = (meeting_date, meeting_url, agenda_url, meeting_soup)

        if not best:
            # No agenda published on any recent meeting page
            return []

        meeting_date, meeting_url, agenda_url, meeting_soup = best

        h1 = meeting_soup.find("h1")
        name = h1.get_text(strip=True) if h1 else "Council meeting"

        page_text = meeting_soup.get_text(" ", strip=True)
        date_str = None
        m = re.search(self.date_regex, page_text)
        if m:
            date_str = m.group()
        else:
            date_str = str(meeting_date)

        time = self._parse_time_from_text(page_text)
        location = self._extract_location(meeting_soup)

        return [ScraperReturn(
            name=name,
            date=date_str,
            time=time,
            webpage_url=meeting_url,
            download_url=agenda_url,
            location=location,
        )]
