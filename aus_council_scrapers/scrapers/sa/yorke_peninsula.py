import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://yorke.sa.gov.au"
_MEETINGS_URL = f"{_BASE_URL}/about-us/meetings/agendas-and-minutes"

# Yorke Peninsula (WordPress, not the LGA SA platform) gives each body a page
# under /about-us/meetings/agendas-and-minutes/. Two are read:
#
# * council/: Council and special Council meetings.
# * dev-assessment-panel/: the Council Assessment Panel, the planning body.
#
# The rest are the audit committee, elected-member workshops and a handful
# of working parties, which are left out.
#
# Each page lists the current year as direct PDF links titled with the
# document and the meeting ("Agenda – Council Meeting – 14 October 2026",
# "Council Assessment Panel Minutes – 23 June 2026"), and links one archive
# page per earlier year. The archive slugs are irregular (`2023-archive-2`,
# CAP's 2020 at `2019-archive-2`, its 2023 under a different parent), so they
# are read off the link text ("2023 archive") rather than built. A
# production run, one year, reads the two current pages: 2 requests.
_BODIES = (
    (f"{_MEETINGS_URL}/council/", None),
    (f"{_MEETINGS_URL}/dev-assessment-panel/", "Council Assessment Panel"),
)

_ARCHIVE_LINK = re.compile(r"^\s*(\d{4})\s+archive\s*$", re.IGNORECASE)

# The council lists more than agendas and minutes beside each meeting:
# separate-cover attachments, supplementary agendas and late reports (not
# the agenda itself), confidential minutes released a year later (filed
# under the release's month, titled with the original meeting), requests
# for and records of special meetings, and panel procedures. Minutes
# "including" a confidential release (worded half a dozen ways) are the
# meeting's minutes, so everything from "including" on is left out of the
# check.
_NOT_A_PAPER = re.compile(
    r"separate cover|attach|confidential|release|supplementary|late report"
    r"|request for|\brecord\b|\bitem\b|terms of reference|procedures|code of conduct",
    re.IGNORECASE,
)
_INCLUDES_RELEASE = re.compile(r"\bincluding\b.*$", re.IGNORECASE)
# "Council Assessment Panel Agenda – 24 November 2020 – Cancelled": a meeting
# that did not happen, so its agenda is not a meeting's paper.
_CANCELLED = re.compile(r"\bcancel+ed\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes?\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october"
    "|november|december"
)
# Not \b at the end: "Council Agenda – 19 January 2022_".
_DATE = re.compile(rf"\b(\d{{1,2}})\s+({_MONTHS})\s+(\d{{4}})(?!\d)", re.IGNORECASE)
# "Minutes – Special Council Meeting – 6 May 2026 (Adjourned from 29 April
# 2026)": the minutes of the 29 April meeting, which was adjourned to 6 May.
_ADJOURNED_FROM = re.compile(
    rf"adjourned from\s+(\d{{1,2}}\s+(?:{_MONTHS})\s+\d{{4}})", re.IGNORECASE
)
_ADJOURNED_TO = re.compile(r"adjourned to", re.IGNORECASE)
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)
_FINAL = re.compile(r"\b(?:final|confirmed)\b", re.IGNORECASE)
_DRAFT = re.compile(r"\b(?:draft|unconfirmed)\b", re.IGNORECASE)


# The panel's 2021-2023 archive pages title papers with the day and month
# only ("Assessment Panel Agenda – November 23", "– 22 June"); the year is
# the archive's own.
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})\s+({_MONTHS})\b", re.IGNORECASE)
_MONTH_DAY = re.compile(rf"\b({_MONTHS})\s+(\d{{1,2}})\b", re.IGNORECASE)


def _month(name: str) -> int:
    return _MONTHS.split("|").index(name.lower()) + 1


def _parse_date(text: str, page_year: Optional[int] = None) -> Optional[datetime.date]:
    try:
        if match := _DATE.search(text):
            return datetime.date(int(match[3]), _month(match[2]), int(match[1]))
        if page_year is None:
            return None
        if match := _DAY_MONTH.search(text):
            return datetime.date(page_year, _month(match[2]), int(match[1]))
        if match := _MONTH_DAY.search(text):
            return datetime.date(page_year, _month(match[1]), int(match[2]))
    except ValueError:
        return None
    return None


def _rank(kind: str, title: str) -> int:
    """Lower is better, among one meeting's agendas or minutes.

    The adjourned special meeting of 29 April 2026 has its agenda twice,
    once reissued "(Adjourned to 6 May 2026)"; the original is kept. The 12
    February 2025 minutes are listed as "(Draft)" and "(Final)"; the final
    set is kept.
    """
    if kind == "agenda":
        return 1 if _ADJOURNED_TO.search(title) else 0
    if _FINAL.search(title):
        return 0
    return 2 if _DRAFT.search(title) else 1


@register_scraper
class YorkePeninsulaScraper(BaseScraper):
    def __init__(self):
        super().__init__("yorke_peninsula", "SA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

    @staticmethod
    def _archives(soup: BeautifulSoup, page_url: str) -> dict[int, str]:
        archives: dict[int, str] = {}
        for link in soup.find_all("a", href=True):
            match = _ARCHIVE_LINK.match(link.get_text(" ", strip=True))
            if match:
                archives.setdefault(int(match[1]), urljoin(page_url, link["href"]))
        return archives

    @staticmethod
    def _papers(
        soup: BeautifulSoup,
        page_url: str,
        body: Optional[str],
        page_year: Optional[int],
    ) -> list[tuple]:
        """(name, date, kind, rank, url) for each agenda or minutes on a page."""
        content = soup.find("main") or soup.body or soup
        papers = []
        for link in content.find_all("a", href=True):
            href = urljoin(page_url, link["href"])
            if not href.lower().endswith(".pdf"):
                continue
            title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            if _NOT_A_PAPER.search(_INCLUDES_RELEASE.sub("", title)):
                continue
            if _CANCELLED.search(title):
                continue
            if _MINUTES.search(title):
                kind = "minutes"
            elif _AGENDA.search(title):
                kind = "agenda"
            else:
                continue
            # Two 2023 minutes are titled with their file name, hyphens for
            # spaces ("Minutes-Council-Meeting-12-April-2023-Including-..."),
            # so dates are read with hyphens and underscores as spaces.
            spaced = re.sub(r"[-_]+", " ", title)
            adjourned_from = _ADJOURNED_FROM.search(spaced)
            date = _parse_date(
                adjourned_from[1] if adjourned_from else spaced, page_year
            )
            if date is None:
                continue
            if body:
                name = body
            elif _SPECIAL.search(title):
                name = "Special Council Meeting"
            else:
                name = "Council Meeting"
            papers.append((name, date, kind, _rank(kind, title), href))
        return papers

    @staticmethod
    def _merge_unlabelled_special(meetings: dict[tuple, dict]) -> None:
        """Fold minutes titled "Council Meeting" into that day's special meeting.

        The 25 May 2022 special meeting's minutes are titled "Minutes –
        Council Meeting – 25 May 2022". Read literally that is an ordinary
        meeting with minutes and no agenda beside a special meeting with an
        agenda and no minutes. Only that complementary shape is merged: two
        records that each hold the same kind of paper are two meetings.
        """
        for name, date in list(meetings):
            if name != "Special Council Meeting":
                continue
            special = meetings[(name, date)]
            plain = meetings.get(("Council Meeting", date))
            if plain is None:
                continue
            if all(not (special[k] and plain[k]) for k in ("agenda", "minutes")):
                for kind in ("agenda", "minutes"):
                    special[kind] = special[kind] or plain[kind]
                del meetings[("Council Meeting", date)]

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        meetings: dict[tuple, dict] = {}
        for listing_url, body in _BODIES:
            current = self._soup(listing_url)
            archives = self._archives(current, listing_url)
            pages = [(listing_url, current, None)]
            for year, archive_url in sorted(archives.items()):
                if year in wanted:
                    pages.append((archive_url, self._soup(archive_url), year))

            found = 0
            for page_url, soup, page_year in pages:
                for name, date, kind, rank, url in self._papers(
                    soup, page_url, body, page_year
                ):
                    found += 1
                    if date.year not in wanted:
                        continue
                    meeting = meetings.setdefault(
                        (name, date),
                        {"page": page_url, "agenda": None, "minutes": None},
                    )
                    if meeting[kind] is None or rank < meeting[kind][0]:
                        meeting[kind] = (rank, url)
            if not found and not archives:
                # A page can be empty early in January, but it always links
                # its archives, so neither papers nor archive links means the
                # layout changed rather than a quiet year.
                raise ValueError(
                    f"{self.council_name}: no agendas or minutes found on {listing_url}"
                )

        self._merge_unlabelled_special(meetings)

        results = []
        for (name, date), meeting in meetings.items():
            agenda = meeting["agenda"][1] if meeting["agenda"] else None
            minutes = meeting["minutes"][1] if meeting["minutes"] else None
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=meeting["page"],
                    agenda_url=agenda,
                    minutes_url=minutes,
                    download_url=agenda or minutes,
                )
            )
        return results
