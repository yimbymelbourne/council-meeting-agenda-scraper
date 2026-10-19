import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.buloke.vic.gov.au"
_INDEX_URL = f"{_BASE_URL}/agendas-minutes-attachments"

# Buloke's elcomCMS site has one page per year (/agendas-minutes-and-
# attachments-2026, back to 2019), linked from an index page. Each is a flat
# list of links to /ArticleDocuments/<id>/<file>.pdf.aspx, which answer with
# the PDF itself.
#
# Labels are hand-typed and carry the meeting: "21 October Ordinary Meeting
# Agenda" (no year since 2025; the page gives it), "19 November 2025
# Statutory Meeting Minutes", "Agenda - 9 December 2020 Ordinary Meeting".
# The date is read from the label and never from the filename: the 16
# September 2026 agenda is filed as "Council Meeting Agenda - 16 September
# 2027.pdf".
_YEAR_PAGE = re.compile(r"/agendas-minutes-and-attachments-(\d{4})/?$")
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ]
    )
}
_DAY_MONTH = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b(?:,?\s+(\d{4}))?",
    re.IGNORECASE,
)
# "Minutes", and once "inutes - 12 May 2021 Ordinary Meeting".
_MINUTES = re.compile(r"minut|^inutes", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
# An addendum or supplementary agenda adds to the meeting's agenda; it is not
# the agenda.
_NOT_THE_AGENDA = re.compile(r"addendum|supplementary|attachment", re.IGNORECASE)
# The kind of meeting, as the labels name it. A label with none ("22
# September Meeting Minutes") belongs to whichever meeting sat that day.
_TYPE = re.compile(r"\b(ordinary|special|additional|statutory)\b", re.IGNORECASE)
# From 2019 to 2024 the files were named by a code, which says the meeting's
# type where the label ("Agenda - 9 October 2024 Council Meeting") does not:
# ORD_09102024_AGN_AT, STAT_20112024_MIN, ORD_21122023_AGN_AT_EXTRA (an extra,
# that is special, meeting).
_CODED_FILE = re.compile(r"(?:^|[^a-z])(ORD|STAT)_\d{8}_(AGN|MIN)", re.IGNORECASE)
_EXTRA = re.compile(r"_EXTRA", re.IGNORECASE)
# What is left of a label that names a meeting and nothing else ("29 October
# Ordinary Council Meeting"): that one is the agenda, filed without the word.
_MEETING_ONLY = re.compile(
    r"^(?:ordinary|special|additional|statutory)?\s*(?:council\s+)?meeting(?:\s+of\s+council)?$",
    re.IGNORECASE,
)


@register_scraper
class BulokeScraper(BaseScraper):
    def __init__(self):
        super().__init__("buloke", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _label_date(label: str, page_year: int) -> Optional[datetime.date]:
        match = _DAY_MONTH.search(label)
        if not match:
            return None
        day, month, year = match.groups()
        try:
            return datetime.date(
                int(year or page_year), _MONTHS[month[:3].lower()], int(day)
            )
        except ValueError:
            return None

    @staticmethod
    def _links(soup: BeautifulSoup) -> list[tuple[str, str]]:
        """(href, label) per document, merging anchors that share an href.

        Each document is linked twice, the second time by an icon with no
        text, and some labels are split over two anchors to the same file
        ("Minutes" + "- 9 October 2024 Council Meeting").
        """
        links: list[tuple[str, str]] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if "/ArticleDocuments/" not in href:
                continue
            # The labels carry non-breaking spaces.
            text = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
            if links and links[-1][0] == href:
                links[-1] = (href, f"{links[-1][1]} {text}".strip())
            elif text:
                links.append((href, text))
        return links

    def _papers(self, url: str, page_year: int):
        """(date, type, type from the file code, kind, document url) per paper."""
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        papers = []
        for href, label in self._links(soup):
            date = self._label_date(label, page_year)
            if date is None:
                self.logger.warning(f"{self.council_name}: undated {label!r} on {url}")
                continue
            filename = unquote(href.rsplit("/", 1)[-1])
            coded = _CODED_FILE.search(filename)
            rest = re.sub(r"\s+", " ", _DAY_MONTH.sub("", label)).strip(" -–—,")
            if _MINUTES.search(label):
                kind = "minutes"
            elif _AGENDA.search(label):
                if _NOT_THE_AGENDA.search(label):
                    continue
                kind = "agenda"
            elif coded:
                kind = "minutes" if coded.group(2).upper() == "MIN" else "agenda"
            elif _MEETING_ONLY.match(rest):
                kind = "agenda"
            else:
                continue
            type_match = _TYPE.search(label)
            coded_type = None
            if coded:
                if coded.group(1).upper() == "STAT":
                    coded_type = "Statutory"
                elif _EXTRA.search(filename):
                    coded_type = "Special"
                else:
                    coded_type = "Ordinary"
            papers.append(
                (
                    date,
                    type_match.group(1).capitalize() if type_match else None,
                    coded_type,
                    kind,
                    urljoin(url, href),
                )
            )
        return papers

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # The index says which years have a page; a year without one (2027
        # until the council makes it) is not requested. Fetch failures are
        # left to raise: each page is a whole year.
        index = BeautifulSoup(
            self.fetcher.fetch_with_requests(_INDEX_URL), "html.parser"
        )
        year_pages = {}
        for link in index.find_all("a", href=True):
            match = _YEAR_PAGE.search(link["href"])
            if match:
                year_pages[int(match.group(1))] = urljoin(_INDEX_URL, link["href"])
        if not year_pages:
            raise RuntimeError(
                f"{self.council_name}: no year pages linked from {_INDEX_URL}"
            )

        meetings: dict[tuple[datetime.date, str], dict] = {}
        untyped = []
        for year in sorted(wanted & set(year_pages)):
            url = year_pages[year]
            for date, meeting_type, coded_type, kind, doc_url in self._papers(
                url, year
            ):
                if date.year not in wanted:
                    continue
                if meeting_type is None:
                    untyped.append((date, coded_type, kind, doc_url, url))
                    continue
                meeting = meetings.setdefault(
                    (date, meeting_type), {"webpage_url": url}
                )
                # First link wins: the page lists the current paper first.
                meeting.setdefault(kind, doc_url)

        # A paper whose label names no meeting type takes the type its file
        # code gives. Failing that, it joins the one meeting held that day:
        # "22 September Meeting Minutes" are the minutes of the 22 September
        # 2025 Special Meeting. With neither it is left untyped ("Agenda - 1
        # July 2020 Council"), not called Ordinary.
        # Coded papers first, so an uncoded one finds them already placed:
        # the 15 February 2023 minutes are uncoded, their agenda is coded.
        untyped.sort(key=lambda paper: paper[1] is None)
        for date, coded_type, kind, doc_url, url in untyped:
            if coded_type:
                key = (date, coded_type)
            else:
                same_day = [key for key in meetings if key[0] == date]
                key = same_day[0] if len(same_day) == 1 else (date, None)
            meetings.setdefault(key, {"webpage_url": url}).setdefault(kind, doc_url)

        results = []
        for (date, meeting_type), papers in sorted(
            meetings.items(), key=lambda item: (item[0][0], item[0][1] or "")
        ):
            agenda_url = papers.get("agenda")
            minutes_url = papers.get("minutes")
            results.append(
                ScraperReturn(
                    name=(
                        f"{meeting_type} Council Meeting"
                        if meeting_type
                        else "Council Meeting"
                    ),
                    date=date.isoformat(),
                    time=None,
                    webpage_url=papers["webpage_url"],
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            # The one empty answer that is not a fault: production asks for
            # the current year alone, and before March a small council may not
            # have posted its first paper of the year. Any other empty result
            # means the pages moved or stopped parsing, and returning [] would
            # read downstream as a successful night with no meetings.
            today = clock.today()
            if min(wanted) > today.year or (
                min(wanted) == today.year and today.month < 3
            ):
                self.logger.warning(
                    f"{self.council_name}: no meetings published yet for "
                    f"{sorted(wanted)}"
                )
            else:
                raise RuntimeError(
                    f"{self.council_name}: no meetings with documents for "
                    f"{sorted(wanted)}; the pages may have changed"
                )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
