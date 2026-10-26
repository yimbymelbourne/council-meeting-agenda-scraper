import datetime
import re
from collections import defaultdict
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.alyka import (
    filename_of,
    filename_says_agenda_only,
    find_date,
)
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

# The shire is nungarin.wa.gov.au. nungarin.com.au, which the council lists
# sometimes carry, is a community site.
_BASE_URL = "https://www.nungarin.wa.gov.au"
_MEETINGS_URL = f"{_BASE_URL}/council/council-meetings.aspx"

# A CouncilConnect (SparkCMS) site, but the meetings module is unused:
# everything is on this one content page, a table per year headed "2026
# Council Meetings", with a row per meeting: Meeting Date | Agenda |
# Attachments | Minutes | Attendance. The links go straight to PDFs under
# /Profiles/nungarin/Assets/ClientData/. robots.txt disallows
# /Profiles/nungarin/Assets/ModuleData/, which none of them use.
#
# The page is hand-maintained, and the row date is the one thing on it that
# can be trusted. File names are not: `AGENDA_-_21_November_2020.pdf` is the
# agenda for 18 November 2020 and `Minutes_-_17_Dec_2020.pdf` the minutes of
# 16 December 2020, as their first pages say. So the row date dates the
# meeting, and file names are only used to settle which row a reused file
# belongs to (see _shared_urls).

_SPECIAL = re.compile(r"\bspecial\b|\bSCM\b", re.IGNORECASE)
_ELECTORS = re.compile(r"elector", re.IGNORECASE)
_AUDIT = re.compile(r"audit", re.IGNORECASE)
# Not the agenda: the notice calling a special meeting, and a late item
# issued separately from the agenda it adds to.
_NOT_AGENDA = re.compile(r"notice|late|attachment", re.IGNORECASE)
_CONFIRMED = re.compile(r"(?<!un)confirmed", re.IGNORECASE)
_TABLE_YEAR = re.compile(r"\b(20\d\d)\s+Council Meetings\b", re.IGNORECASE)
# Rows whose date is wrong, checked against the papers: keyed on a file the
# row links, so the correction cannot move another row. The row reads 17
# June 2024; its agenda (June_Agenda_2024.pdf) calls the meeting for "19
# June 2024 at 4.30 pm" and its minutes are OCMM_19_June_2024_Confirmed.pdf.
_DATE_CORRECTIONS = {
    "June_Agenda_2024.pdf": (datetime.date(2024, 6, 17), datetime.date(2024, 6, 19)),
}


def _spaced(name: str) -> str:
    return re.sub(r"[-_.]+", " ", name)


def _meeting_type(text: str) -> str:
    if _ELECTORS.search(text):
        return "Annual Electors Meeting"
    if _AUDIT.search(text):
        return "Finance and Audit Committee"
    if _SPECIAL.search(text):
        return "Special Council Meeting"
    return "Ordinary Council Meeting"


def _names_date(filename: str, date: datetime.date) -> bool:
    """Whether a file name carries this meeting's date in any of its forms.

    `Audit_Minutes_25_March_2021.pdf`, `SCM_Minutes_08082024_-_Unconfirmed.pdf`,
    `Special_council_Meeting_16_01_2026.pdf`.
    """
    spaced = _spaced(filename)
    found = find_date(spaced)
    if found and found[0] == date:
        return True
    digits = re.sub(r"\D+", " ", filename)
    forms = {
        f"{date.day:02d} {date.month:02d} {date.year}",
        f"{date.day:02d} {date.month:02d} {date.year % 100:02d}",
        f"{date.day:02d}{date.month:02d}{date.year}",
    }
    return any(f" {form} " in f" {digits} " for form in forms)


def _names_month(filename: str, date: datetime.date) -> bool:
    return date.strftime("%B").lower() in filename.lower()


@register_scraper
class NungarinScraper(BaseScraper):
    def __init__(self):
        super().__init__("nungarin", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _pdf_links(cell) -> list[tuple[str, str]]:
        links = []
        for anchor in cell.find_all("a", href=True):
            label = anchor.get_text(" ", strip=True)
            if not label:
                # An unlabelled link is a stray: the 19 April 2023 audit
                # committee row carries one to that day's Council minutes,
                # and 15 May 2024's is a second copy of the agenda.
                continue
            url = urljoin(_MEETINGS_URL, anchor["href"].strip())
            # A few links stop at a folder (".../ClientData/Audit") and serve
            # nothing; recordings are .mp4.
            if filename_of(url).lower().endswith(".pdf"):
                links.append((label, url))
        return links

    @staticmethod
    def _row_date(text: str, table_year: Optional[int], links) -> Optional[datetime.date]:
        found = find_date(text)
        if not found:
            return None
        date = found[0]
        for _, url in links:
            wrong, right = _DATE_CORRECTIONS.get(filename_of(url), (None, None))
            if date == wrong:
                return right
        if table_year and date.year != table_year:
            # "19 August 2019" sits in the 2020 table and links
            # `AGENDA_-_19_August_2020.pdf` and `MINUTES_-_19_August_2020.pdf`:
            # a typo in the row's year. Corrected only when a file names the
            # table's year with the same day, since rows do legitimately
            # cross over—16 January 2026 is in the 2025 table as well.
            try:
                moved = date.replace(year=table_year)
            except ValueError:
                return date
            if any(_names_date(filename_of(url), moved) for _, url in links):
                return moved
        return date

    def _meetings(self, soup) -> dict[tuple, dict[str, list[str]]]:
        """``{(date, type): {"agenda": [url, ...], "minutes": [url, ...]}}``

        Each list is in order of preference. A meeting can appear twice—16
        January 2026 is in both the 2025 and 2026 tables, and 17 July 2024 has
        two rows—so rows with the same date and type are merged.
        """
        tables = soup.select("table")
        if not tables:
            raise ValueError(f"{self.council_name}: no meeting tables on {_MEETINGS_URL}")
        meetings: dict[tuple, dict[str, list[str]]] = defaultdict(lambda: {"agenda": [], "minutes": []})
        for table in tables:
            heading = table.find_previous(string=_TABLE_YEAR)
            table_year = int(_TABLE_YEAR.search(heading).group(1)) if heading else None
            rows = table.find_all("tr")
            if not rows:
                continue
            header = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
            try:
                agenda_col = header.index("agenda")
                minutes_col = header.index("minutes")
            except ValueError:
                continue
            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells) <= max(agenda_col, minutes_col):
                    continue
                agenda_links = self._pdf_links(cells[agenda_col])
                minutes_links = self._pdf_links(cells[minutes_col])
                if not agenda_links and not minutes_links:
                    # Meetings scheduled later in the year, and the April 2023
                    # meeting whose links point at a folder.
                    continue
                date = self._row_date(
                    cells[0].get_text(" ", strip=True), table_year, agenda_links + minutes_links
                )
                if date is None:
                    self.logger.warning(
                        f"{self.council_name}: cannot date row {cells[0].get_text(' ', strip=True)!r}; skipped"
                    )
                    continue
                kind_text = cells[agenda_col].get_text(" ", strip=True) or cells[
                    minutes_col
                ].get_text(" ", strip=True)
                papers = meetings[(date, _meeting_type(kind_text))]

                for label, url in agenda_links:
                    if _NOT_AGENDA.search(label) or _NOT_AGENDA.search(filename_of(url)):
                        continue
                    if url not in papers["agenda"]:
                        papers["agenda"].append(url)

                # Confirmed minutes first, then whatever else the cell offers
                # (unconfirmed, or a label that says neither).
                ranked = sorted(
                    (
                        (label, url)
                        for label, url in minutes_links
                        # The 21 October 2020 "Minutes" link is the agenda.
                        if not filename_says_agenda_only(url)
                    ),
                    key=lambda link: not (
                        _CONFIRMED.search(link[0]) or _CONFIRMED.search(filename_of(link[1]))
                    ),
                )
                for _, url in ranked:
                    if url not in papers["minutes"]:
                        papers["minutes"].append(url)
        return meetings

    def _shared_urls(self, meetings: dict[tuple, dict[str, list[str]]]) -> None:
        """Take a file linked from several meetings off all but its own.

        The council reuses file names, so one URL can sit under several rows
        and only the last upload survives at it: `.../2021/Agenda.pdf` is the
        agenda link for four 2021 meetings, `Minutes.pdf` for two. And a row
        sometimes links its neighbour's file—September 2024's "Minutes
        (Confirmed)" is `OCM_Minutes_August_2024_-_Confirmed.pdf`. A shared
        file stays only on the one meeting whose date (or failing that,
        month) its name carries, and comes off every row when none or several
        match. The next link in the cell, often the unconfirmed copy, then
        stands in.
        """
        # A file named for another meeting of the same type belongs to that
        # meeting: the 9 March 2021 audit committee row links
        # `Audit_Minutes_25_March_2021.pdf`, and 25 March has its own row.
        # Only then, because the row date and the file name disagree often
        # enough on their own (see the module comment).
        for key, papers in meetings.items():
            others = [k for k in meetings if k != key and k[1] == key[1]]
            for urls in papers.values():
                for url in list(urls):
                    filename = filename_of(url)
                    if not _names_date(filename, key[0]) and any(
                        _names_date(filename, other[0]) for other in others
                    ):
                        urls.remove(url)

        owners: dict[str, set[tuple]] = defaultdict(set)
        for key, papers in meetings.items():
            for urls in papers.values():
                for url in urls:
                    owners[url].add(key)
        for url, keys in owners.items():
            if len(keys) < 2:
                continue
            filename = filename_of(url)
            claim = {key for key in keys if _names_date(filename, key[0])} or {
                key for key in keys if _names_month(filename, key[0])
            }
            keep = claim if len(claim) == 1 else set()
            for key in keys - keep:
                for urls in meetings[key].values():
                    if url in urls:
                        urls.remove(url)
            self.logger.info(
                f"{self.council_name}: {filename} is linked from {len(keys)} meetings; "
                f"kept on {sorted(k[0].isoformat() for k in keep) or 'none'}"
            )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Left to raise: the page is the only request, and an empty result
        # would report a blocked site as a council with no meetings. The host
        # is behind Cloudflare, with no challenge seen from a home connection.
        html = self.fetcher.fetch_with_requests(_MEETINGS_URL)
        meetings = self._meetings(BeautifulSoup(html, "html.parser"))
        self._shared_urls(meetings)

        results = []
        for (date, name), papers in sorted(meetings.items()):
            if date.year not in wanted:
                continue
            agenda_url = papers["agenda"][0] if papers["agenda"] else None
            minutes_url = papers["minutes"][0] if papers["minutes"] else None
            if not agenda_url and not minutes_url:
                continue
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_MEETINGS_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            # The one legitimate empty answer: a run for the current year in
            # its first quarter, before any of its papers are up (or for a
            # later year). Anything else means the site changed, and [] would
            # be recorded as a successful scrape.
            this_year = clock.current_year()
            if all(y > this_year or (y == this_year and clock.today().month <= 3) for y in wanted):
                self.logger.warning(f"{self.council_name}: no meetings published yet for {sorted(wanted)}")
            else:
                raise RuntimeError(f"{self.council_name}: found no meetings for {sorted(wanted)}")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
