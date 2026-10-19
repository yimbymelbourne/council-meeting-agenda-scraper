import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_LISTING_URL = "https://www.cobar.nsw.gov.au/council/about-council/council-meetings/"

# Every Council meeting since 2014 is on this one page: an Elementor accordion
# with one item per year, each holding a table whose rows are Month | Date |
# Business Papers | Attachments | Supplementary Reports | Minutes. A whole
# history is one request, so a production year costs the same as a full run.
#
# The columns cannot be trusted: in late 2024 the minutes sit in the
# Supplementary Reports column, and the Business Papers cell also carries
# tabled and late reports. So documents are picked by their link text, which
# is consistent—"Agenda", "Ordinary Agenda", "Extraordinary Agenda" for the
# business paper and a bare "Minutes" for the minutes. "Clause 3 – Meeting
# Minutes" and "April Ordinary Council Meeting Minutes" are attachments that
# carry another body's or meeting's minutes, and do not match.
#
# The separate Committee Meetings page is not read: this project tracks the
# Council's own meetings.
_AGENDA_TEXT = re.compile(
    r"^(?:ordinary|extraordinary)?\s*agenda(?:\s*\+\s*attachments)?$", re.IGNORECASE
)
_MINUTES_TEXT = re.compile(r"^minutes$", re.IGNORECASE)

# Links on the page whose files are gone: each answers 301 to the home page
# (checked 20 Oct 2026), so emitting them would hand on a web page as the
# paper. They are dropped, and the October and November 2022 meetings, which
# have no other paper, with them.
_DEAD = {
    "https://www.cobar.nsw.gov.au/wp-content/uploads/2021/11/28.05.2020_-_Ordinary_Council_Meeting_Agenda.pdf",
    "https://www.cobar.nsw.gov.au/wp-content/uploads/2022/10/October-Ordinary-Meeting-Minutes-Signed.pdf",
    "https://www.cobar.nsw.gov.au/wp-content/uploads/2022/11/November-Ordinary-Meeting-Agenda.pdf",
}

_MONTHS = {
    m: i
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
        ],
        start=1,
    )
}

# Dates written into file names: "26.03.2020", "12.12.19", "14042021",
# "26-February-2026", "27_August_2020".
_DOTTED = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?!\d)")
_COMPACT = re.compile(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)")
_WORDED = re.compile(
    r"(?<!\d)(\d{1,2})[-_ ]+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[-_ ]+(\d{4})",
    re.IGNORECASE,
)


def _file_name(url: str) -> str:
    return unquote(url.rsplit("/", 1)[-1])


def _named_dates(url: str) -> set[datetime.date]:
    name = _file_name(url)
    found = set()
    candidates = [(d, m, y) for d, m, y in _DOTTED.findall(name)]
    candidates += [(d, m, y) for d, m, y in _COMPACT.findall(name)]
    candidates += [(d, _MONTHS[m[:3].lower()], y) for d, m, y in _WORDED.findall(name)]
    for day, month, year in candidates:
        year = int(year)
        if year < 100:
            year += 2000
        try:
            found.add(datetime.date(year, int(month), int(day)))
        except ValueError:
            pass
    return found


def _names_another_meeting(url: str, date: datetime.date) -> bool:
    """True when the file name dates the document to some other meeting.

    The page links several documents from the wrong row: the February 2021
    minutes are "10.12.2020_-_Council_Meeting_Minutes.pdf" and the March 2021
    agenda is "28.03.2019_-_Ordinary_Council_Meeting_Agenda.pdf". A name
    agrees if it is within a month of the row—agendas are dated when they are
    issued, and the March 2020 minutes are those of the meeting adjourned to
    9 April—or on the same day and month, because the year is sometimes
    mistyped (the February 2019 agenda is filed as 28.02.2018). A file with
    no date in its name cannot disagree.
    """
    named = _named_dates(url)
    return bool(named) and not any(
        abs((d - date).days) <= 31 or (d.month, d.day) == (date.month, date.day)
        for d in named
    )


def _kind_from_file(url: str) -> Optional[str]:
    name = _file_name(url).lower()
    agenda = "agenda" in name
    minutes = "minute" in name
    if agenda and not minutes:
        return "agenda"
    if minutes and not agenda:
        return "minutes"
    return None


@register_scraper
class CobarScraper(BaseScraper):
    def __init__(self):
        super().__init__("cobar", "NSW", "https://www.cobar.nsw.gov.au")

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _row_documents(self, row) -> tuple[Optional[str], Optional[str], str]:
        agenda_url = minutes_url = None
        agenda_label = ""
        for link in row.find_all("a", href=True):
            text = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
            # Rows before mid-2023 link relative paths.
            href = urljoin(_LISTING_URL, link["href"].strip())
            if not urlsplit(href).netloc.endswith("cobar.nsw.gov.au"):
                # The May 2023 agenda links the web developer's staging
                # site, which no longer resolves.
                continue
            if href in _DEAD:
                continue
            if agenda_url is None and _AGENDA_TEXT.match(text):
                # The minutes are sometimes uploaded under the agenda's
                # link and vice versa (the June 2014 agenda is the minutes).
                if _kind_from_file(href) != "minutes":
                    agenda_url, agenda_label = href, text
            elif minutes_url is None and _MINUTES_TEXT.match(text):
                # August and September 2025 "Minutes" link the agenda.
                if _kind_from_file(href) != "agenda":
                    minutes_url = href
        return agenda_url, minutes_url, agenda_label

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        html = self.fetcher.fetch_with_requests(_LISTING_URL)
        soup = BeautifulSoup(html, "html.parser")

        records: list[tuple[datetime.date, str, Optional[str], Optional[str]]] = []
        years_seen = set()
        for item in soup.select(".elementor-accordion-item"):
            title = item.select_one(".elementor-tab-title")
            content = item.select_one(".elementor-tab-content")
            if not title or not content:
                continue
            year_match = re.search(r"\b(20\d{2})\b", title.get_text(" ", strip=True))
            if not year_match:
                continue
            year = int(year_match.group(1))
            years_seen.add(year)
            if year not in wanted or year < EARLIEST_YEAR:
                continue

            for row in content.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) < 3:
                    continue
                month_text = cells[0].get_text(" ", strip=True)
                day_text = cells[1].get_text(" ", strip=True)
                month_match = re.match(r"([A-Za-z]{3})", month_text)
                if not month_match or month_match.group(1).lower() not in _MONTHS:
                    continue  # the header row
                agenda_url, minutes_url, agenda_label = self._row_documents(row)
                if not agenda_url and not minutes_url:
                    continue
                if not re.fullmatch(r"\d{1,2}", day_text):
                    self.logger.warning(
                        f"{self.council_name}: {month_text} {year} has papers but "
                        f"no day ({day_text!r}); left out"
                    )
                    continue
                date = datetime.date(
                    year, _MONTHS[month_match.group(1).lower()], int(day_text)
                )

                if agenda_url and _names_another_meeting(agenda_url, date):
                    agenda_url = None
                if minutes_url and _names_another_meeting(minutes_url, date):
                    minutes_url = None
                if not agenda_url and not minutes_url:
                    continue

                # The type is in the month cell ("September (Extraordinary)"),
                # the agenda's label, or only the file name: the 15 June 2022
                # extraordinary meeting's paper is labelled "Ordinary Agenda".
                evidence = " ".join(
                    [month_text, agenda_label]
                    + [_file_name(u) for u in (agenda_url, minutes_url) if u]
                ).lower()
                name = (
                    "Extraordinary Council Meeting"
                    if re.search(r"extra[\s_-]*ordinary", evidence)
                    else "Ordinary Council Meeting"
                )
                records.append((date, name, agenda_url, minutes_url))

        if not years_seen:
            raise ValueError(
                f"{self.council_name}: no year sections found on {_LISTING_URL}"
            )

        results = self._resolve(records)
        if not results:
            self.logger.warning(
                f"{self.council_name}: no meetings with papers for {sorted(wanted)} "
                f"on {_LISTING_URL}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    def _resolve(self, records) -> list[ScraperReturn]:
        # The 2024 year appears twice on the page with the same table, so the
        # same row arrives twice.
        unique = list(dict.fromkeys(records))

        # A document linked from two different rows belongs to at most one of
        # them: the 27 October 2022 row links the 13 October agenda. Keep it on
        # the row its file name dates exactly, and on neither if the name
        # cannot tell them apart.
        claims: dict[str, set[datetime.date]] = {}
        for date, _, agenda_url, minutes_url in unique:
            for url in (agenda_url, minutes_url):
                if url:
                    claims.setdefault(url, set()).add(date)

        def keep(url: Optional[str], date: datetime.date) -> Optional[str]:
            if not url or len(claims[url]) == 1:
                return url
            return url if date in _named_dates(url) else None

        results = []
        for date, name, agenda_url, minutes_url in unique:
            agenda_url = keep(agenda_url, date)
            minutes_url = keep(minutes_url, date)
            if not agenda_url and not minutes_url:
                continue
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return results
