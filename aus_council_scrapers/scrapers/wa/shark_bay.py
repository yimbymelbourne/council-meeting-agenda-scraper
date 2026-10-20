import re
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper

_BASE_URL = "https://www.sharkbay.wa.gov.au"
_SECTION = f"{_BASE_URL}/council/council-and-committee-meetings"

# Shark Bay runs Market Creations' CouncilConnect CMS but not its meetings
# module (/council-meetings/past is a 404). Each body has one hand-edited
# content page instead, holding every year it has kept: Ordinary Council
# from 2021, Special Council from 2016 and the Audit, Risk and Improvement
# Committee from 2019. Three requests cover everything, so a production year
# costs the same three. The older minutes in the document centre
# (/documents/minutes/<year>) stop in 2020 and are labelled by month only,
# so they are not read.
_PAGES = (
    (
        "Ordinary Council Meeting",
        f"{_BASE_URL}/council/council-committee-meetings/ordinary-council-meetings.aspx",
    ),
    ("Special Council Meeting", f"{_SECTION}/special-council-meetings.aspx"),
    (
        "Audit, Risk and Improvement Committee Meeting",
        # The page moved one level down; the old address 301s to this one.
        f"{_SECTION}/audit-risk-and-improvement-committee-meetings/"
        "audit-risk-and-improvement-committee-meetings.aspx",
    ),
)

# Each page is a run of paragraphs, edited by hand year after year, so the
# markup is different in every stretch (spans, <strong>, <h4>, a few
# tables). What holds throughout is the order: a year ("2025"), then a
# meeting's date on a line of its own ("29 October 2025"), then that
# meeting's links. So the page is read as a stream, and each link belongs to
# the last date line above it. The date line is the meeting's: link labels
# are not ("26 July 2026 OCM Minutes" sits under the 29 July meeting), nor
# are filenames (the 29 October 2025 papers are AgendaOCM10092025.pdf).
# One line carries the time in front ("1:00 pm 2 June 2022", the June 2022
# ARIC meeting), so a leading time is allowed and ignored.
_DATE_LINE = re.compile(
    r"^(?:\d{1,2}[:.]\d{2}\s*[ap]\.?m\.?\s+)?(\d{1,2}\s+[A-Za-z]+\s+\d{4})$",
    re.IGNORECASE,
)
# A year, or a month with no day ("December", the 15 December 2021 minutes):
# the links under it have no meeting date to go on, so none is guessed.
_NO_DATE_LINE = re.compile(
    r"^(?:\d{4}|January|February|March|April|May|June|July|August|September|"
    r"October|November|December)$",
    re.IGNORECASE,
)

_AGENDA = re.compile(r"agenda", re.IGNORECASE)
_MINUTES = re.compile(r"minute", re.IGNORECASE)
# Report attachments, annual reports and budgets sit beside the papers.
_EXTRA = re.compile(r"attachment|annual report|budget|plan\b", re.IGNORECASE)
_UNCONFIRMED = re.compile(r"unconfirmed", re.IGNORECASE)

# Date lines that are wrong, found by reading the PDFs. Keyed by filename;
# the value is the date the paper itself gives.
_MISDATED = {
    # Under "4 December 2022"; the minutes are of 14 December 2022.
    "Minutes14122022.pdf": "2022-12-14",
}


@register_scraper
class SharkBayScraper(BaseScraper):
    def __init__(self):
        super().__init__("shark_bay", "WA", _BASE_URL)

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        years_filter = getattr(self, "years_filter", None)
        results: list[ScraperReturn] = []
        for name, url in _PAGES:
            html = self.fetcher.fetch_with_requests(url)
            for date, papers in self._meetings(html, url).items():
                if years_filter and int(date[:4]) not in years_filter:
                    continue
                results.extend(self._records(name, date, papers, url))
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    def _meetings(
        self, html: str, page_url: str
    ) -> dict[str, dict[str, list[tuple[str, bool]]]]:
        """Date -> kind -> [(url, unconfirmed)], in page order."""
        soup = BeautifulSoup(html, "html.parser")
        main = soup.select_one("#maincontent") or soup
        meetings: dict[str, dict[str, list[tuple[str, bool]]]] = {}
        current: Optional[str] = None
        skipped_sharepoint = 0

        for element in main.descendants:
            if isinstance(element, NavigableString):
                if element.find_parent("a"):
                    continue
                text = " ".join(element.split())
                date_line = _DATE_LINE.match(text)
                if date_line:
                    try:
                        current = (
                            parse_date(date_line.group(1), dayfirst=True)
                            .date()
                            .isoformat()
                        )
                    except (ValueError, OverflowError):
                        current = None
                elif _NO_DATE_LINE.match(text):
                    current = None
                continue
            if element.name != "a" or not element.get("href"):
                continue

            href = urljoin(page_url, element["href"].strip())
            host = urlparse(href).netloc
            filename = unquote(urlparse(href).path.rsplit("/", 1)[-1])
            label = element.get_text(" ", strip=True)
            if host.endswith("sharepoint.com"):
                # A handful of papers are SharePoint share links: a viewer
                # page, not the PDF, on a host whose robots.txt is
                # "Disallow: /".
                skipped_sharepoint += 1
                continue
            if not filename.lower().endswith(".pdf") or _EXTRA.search(label):
                continue
            # Some links have no label, or only a date ("30 September
            # 2026"); the filename names the paper then.
            if _MINUTES.search(label):
                kind = "minutes"
            elif _AGENDA.search(label):
                kind = "agenda"
            elif _MINUTES.search(filename):
                kind = "minutes"
            elif _AGENDA.search(filename):
                kind = "agenda"
            else:
                continue

            date = _MISDATED.get(filename, current)
            if date is None:
                self.logger.warning(
                    f"{self.council_name}: {filename} on {page_url} has no meeting "
                    f"date above it; leaving it out"
                )
                continue
            papers = meetings.setdefault(date, {"agenda": [], "minutes": []})
            # The September 2026 agenda is linked twice, once unlabelled.
            if all(href != url for url, _ in papers[kind]):
                unconfirmed = bool(_UNCONFIRMED.search(f"{label} {filename}"))
                papers[kind].append((href, unconfirmed))

        if skipped_sharepoint:
            self.logger.info(
                f"{self.council_name}: left out {skipped_sharepoint} SharePoint "
                f"link(s) on {page_url}"
            )
        return meetings

    def _records(self, name, date, papers, page_url) -> list[ScraperReturn]:
        agendas = self._settle(papers["agenda"])
        minutes = self._settle(papers["minutes"])
        # Two special meetings were held on 12 August 2021 (the CEO's
        # appointment and the budget), each with its own minutes under the
        # one date line, so a date can carry more than one meeting.
        count = max(len(agendas), len(minutes))
        records = []
        for i in range(count):
            agenda_url = agendas[i] if i < len(agendas) else None
            minutes_url = minutes[i] if i < len(minutes) else None
            records.append(
                ScraperReturn(
                    name=name,
                    date=date,
                    time=None,
                    webpage_url=page_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return records

    @staticmethod
    def _settle(entries: list[tuple[str, bool]]) -> list[str]:
        """Drop unconfirmed minutes where the confirmed set is also linked."""
        confirmed = [url for url, unconfirmed in entries if not unconfirmed]
        return confirmed or [url for url, _ in entries[:1]]
