import datetime
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://wagait.nt.gov.au"
_MEETINGS_URL = f"{_BASE_URL}/meetings/"

# Everything is on one WordPress/Elementor page: a heading per section
# ("COUNCIL AGENDA", "COUNCIL MINUTES", then the Finance, Audit and Emergency
# Management committees), each followed by an accordion with a panel per
# year holding a flat run of document links. Agendas and minutes are in
# separate sections, so they are paired here by meeting date.
#
# Only the two council sections are read. The committee sections are not
# council meetings, and their labels disagree with their files often enough
# to make pairing guesswork ("AGENDA 14 May 2024" links to the 5 March 2024
# audit agenda).
_SECTIONS = {"COUNCIL AGENDA": "agenda", "COUNCIL MINUTES": "minutes"}

# Link labels are hand-typed and often lack the day or year ("AGENDA
# November 2023", "WSC-MEETING AGENDA 19 OCTOBER"); the file name usually
# has it ("WSC-Meeting-Agenda-21-November-2023-combined.pdf"). Where both
# carry a full date and disagree, the file name wins—it describes the
# document actually linked: "MINUTES 18 March 2024" links to
# `WSC-MEETING-MINUTES-19-MARCH-2024-.pdf`, and the agenda is 19 March too.
_MONTH = (
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
)
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
_ISO_DATE = re.compile(r"(?<!\d)(20\d\d)[-.](\d\d)[-.](\d\d)(?!\d)")
_DAY_MONTH = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s_\-]*" + _MONTH + r"(?:[\s_\-,]*(\d{4}))?",
    re.IGNORECASE,
)
_MONTH_ONLY = re.compile(r"(?<![a-z])" + _MONTH + r"(?:[\s_\-,]*(\d{4}))?", re.IGNORECASE)
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
# "October 2021 attachments – Policies" is not an agenda, but
# `WSC_Meeting_Agenda_15_June_2021-with-attachments-for-webside.pdf` is.
_ATTACHMENT = re.compile(r"(?<!with[\s_\-])attachment", re.IGNORECASE)
# How far apart an agenda and minutes can be dated and still be one meeting;
# see _pair_moved_meetings.
_MOVED_MEETING_DAYS = 2
_SPECIAL = re.compile(r"special", re.IGNORECASE)


@dataclass
class _Document:
    kind: str  # "agenda" or "minutes"
    url: str
    special: bool
    date: Optional[datetime.date]
    # (year, month) when only the month could be read.
    month: Optional[tuple[int, int]]
    # The accordion panel it sits in, for documents with no date at all.
    panel_year: int


def _full_date(text: str, panel_year: int) -> Optional[datetime.date]:
    match = _ISO_DATE.search(text)
    if match:
        try:
            return datetime.date(*(int(g) for g in match.groups()))
        except ValueError:
            pass
    for day, month, year in _DAY_MONTH.findall(text):
        try:
            return datetime.date(
                int(year or panel_year), _MONTHS[month[:3].lower()], int(day)
            )
        except ValueError:
            continue
    return None


def _month(text: str, panel_year: int) -> Optional[tuple[int, int]]:
    match = _MONTH_ONLY.search(text)
    if not match:
        return None
    return int(match.group(2) or panel_year), _MONTHS[match.group(1)[:3].lower()]


@register_scraper
class WagaitScraper(BaseScraper):
    def __init__(self):
        super().__init__("wagait", "NT", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _links(panel) -> list[tuple[str, str]]:
        """(href, label) per document, merging anchors that share an href.

        One label is split over two anchors to the same file ("SPECIAL ME" +
        "ETING AGENDA 29 June 2026"). An anchor with no text at all is an
        older upload left behind next to its replacement (the April 2025
        draft minutes beside the confirmed ones), so it is dropped.
        """
        links: list[tuple[str, str]] = []
        for anchor in panel.find_all("a", href=True):
            href = anchor["href"].strip()
            text = anchor.get_text(" ", strip=True)
            if links and links[-1][0] == href:
                links[-1] = (href, links[-1][1] + text)
            elif text:
                links.append((href, text))
        return links

    def _documents(self, soup) -> list[_Document]:
        documents = []
        for accordion in soup.select(".elementor-accordion"):
            heading = accordion.find_previous(class_="elementor-heading-title")
            kind = _SECTIONS.get(heading.get_text(" ", strip=True).upper()) if heading else None
            if not kind:
                continue
            for item in accordion.select(".elementor-accordion-item"):
                title = item.select_one(".elementor-tab-title")
                panel = item.select_one(".elementor-tab-content")
                year_text = title.get_text(strip=True) if title else ""
                if not panel or not re.fullmatch(r"\d{4}", year_text):
                    # Elementor's unused "Accordion Title" placeholder.
                    continue
                panel_year = int(year_text)
                for href, label in self._links(panel):
                    url = urljoin(_MEETINGS_URL, href)
                    # One 2020 agenda link points at a news page.
                    if not url.lower().endswith(".pdf"):
                        continue
                    filename = unquote(url.rsplit("/", 1)[-1])
                    text = f"{label} {filename}"
                    if kind == "agenda" and (
                        not _AGENDA.search(text) or _ATTACHMENT.search(text)
                    ):
                        continue
                    date = _full_date(filename, panel_year) or _full_date(label, panel_year)
                    documents.append(
                        _Document(
                            kind=kind,
                            url=url,
                            special=bool(_SPECIAL.search(text)),
                            date=date,
                            month=None if date else (_month(filename, panel_year) or _month(label, panel_year)),
                            panel_year=panel_year,
                        )
                    )
        return documents

    @staticmethod
    def _resolve_months(documents: list[_Document]) -> None:
        """Date a month-only document from its counterpart in the other section.

        "AGENDA October 2021" links to `Website-Copy-Agenda.pdf`, with no day
        anywhere; "MINUTES 19 October 2021" dates that meeting. Only resolved
        when exactly one meeting of that type falls in that month.
        """
        for doc in documents:
            if doc.date or not doc.month:
                continue
            candidates = {
                other.date
                for other in documents
                if other.kind != doc.kind
                and other.date
                and other.special == doc.special
                and (other.date.year, other.date.month) == doc.month
            }
            if len(candidates) == 1:
                doc.date = candidates.pop()

    @staticmethod
    def _pair_moved_meetings(
        meetings: dict[tuple[datetime.date, bool], dict[str, str]],
    ) -> None:
        """Join an agenda and minutes dated a day or two apart.

        The August 2021 agenda is for Tuesday 17 August; the minutes record
        the meeting as held on Wednesday 18 August. Left alone that is two
        half-meetings. An agenda-only meeting is joined to a minutes-only
        one of the same type only when each is the sole candidate for the
        other, and the minutes' date is kept, because the minutes record
        when the meeting actually sat.
        """
        def lone(kind: str) -> list[tuple[datetime.date, bool]]:
            return [key for key, papers in meetings.items() if set(papers) == {kind}]

        for agenda_key in lone("agenda"):
            date, special = agenda_key
            near = [
                key
                for key in lone("minutes")
                if key[1] == special
                and abs((key[0] - date).days) <= _MOVED_MEETING_DAYS
            ]
            if len(near) != 1:
                continue
            minutes_key = near[0]
            rivals = [
                key
                for key in lone("agenda")
                if key[1] == special
                and abs((key[0] - minutes_key[0]).days) <= _MOVED_MEETING_DAYS
            ]
            if rivals != [agenda_key]:
                continue
            meetings[minutes_key]["agenda"] = meetings.pop(agenda_key)["agenda"]

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Left to raise on failure: this page is the scraper's only request,
        # and returning nothing would report a blocked or broken site as a
        # council with no meetings.
        html = self.fetcher.fetch_with_requests(_MEETINGS_URL)

        documents = self._documents(BeautifulSoup(html, "html.parser"))
        self._resolve_months(documents)

        meetings: dict[tuple[datetime.date, bool], dict[str, str]] = {}
        for doc in documents:
            if not doc.date:
                # Said out loud when it could be a wanted meeting: a new
                # label like "AGENDA Special Meeting" over an undated file
                # name would otherwise vanish. Today the only undated paper
                # is a 2019 special meeting's minutes, filed in 2020.
                year = doc.month[0] if doc.month else doc.panel_year
                if year in wanted:
                    self.logger.warning(
                        f"{self.council_name}: cannot date {doc.kind} {doc.url}; skipped"
                    )
                continue
            if doc.date.year not in wanted:
                continue
            papers = meetings.setdefault((doc.date, doc.special), {})
            # First link wins: a panel lists the current upload first.
            papers.setdefault(doc.kind, doc.url)
        self._pair_moved_meetings(meetings)

        results = []
        for (date, special), papers in sorted(meetings.items()):
            agenda_url = papers.get("agenda")
            minutes_url = papers.get("minutes")
            results.append(
                ScraperReturn(
                    name="Special Council Meeting" if special else "Ordinary Council Meeting",
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_MEETINGS_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
