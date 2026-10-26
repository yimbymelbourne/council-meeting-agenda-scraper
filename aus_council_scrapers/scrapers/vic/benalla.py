import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.benalla.vic.gov.au"
# /council-agendas-minutes/ 301s here.
_LISTING_URL = (
    f"{_BASE_URL}/council/councillor-info-and-council-meetings/council-agendas-minutes/"
)

# Benalla Rural City (a bespoke WordPress theme) lists every meeting it keeps
# on one page: an `h3` per body and year ("Council Meetings 2026", "Finance
# and Planning Committee Meetings 2025"), then a download block per meeting,
# `div.nn-block-download`, headed by an `h4` such as "14 October 2026 –
# Council Meeting". Each row in the block is a label ("Agenda", "Minutes",
# "Unconfirmed Minutes", "Item 4.3 – Attachment A – ...") and a link to a PDF
# under /wp-content/uploads/. The next meeting sits above the year sections,
# under "Current meeting cycle". On 26 Oct 2026 the page held February 2025
# to October 2026; older papers are only in the site's document search, which
# this does not read (KNOWN_GAPS in conformance.py).
#
# Only rows labelled exactly Agenda or (Confirmed/Unconfirmed) Minutes are
# taken; item attachments and the budget documents filed beside the papers
# are not. The council's labels are loose about confirmed and unconfirmed
# minutes, so that word is ignored.
#
# Where a heading gives no year ("30 April – Additional Council Meeting") it
# comes from the section heading. "Current meeting cycle" has no year, so
# there it comes from a paper in the block whose file name gives the same
# day and month, or else is the year that puts the date nearest today (the
# block holds the next meeting).
#
# A paper whose file name carries a full date other than its block's may be
# misfiled: the 15 October 2025 Finance and Planning block links
# "Agenda-Additional-Council-Meeting-21-October-2025-1.pdf", whose cover is
# the 21 October 2025 Additional Council Meeting agenda (that meeting's own
# Agenda row has no link). Such a paper moves to the one meeting on the date
# its file name gives that lacks that paper. If no meeting is listed on that
# date (a meeting moved but its file kept the old date, say) it stays in its
# own block. Only when a meeting on that date exists but cannot take it is it
# left out, with a warning.
#
# One request covers every year, so `years_filter` only trims the output.
#
# The server sends its leaf certificate without the RapidSSL intermediate
# that signed it, so requests cannot verify it with certifi alone; the
# intermediate is shipped in aus_council_scrapers/certs/ and trusted for
# this scraper's requests only (`extra_ca_certs`). The leaf expires 13 Jan
# 2027 and may renew under a different intermediate, so re-check the chain
# before then (issue #192). council-alerts' summariser fetches these PDFs with
# Node, which has the same gap (yimbymelbourne/council-alerts#87).
#
# robots.txt (checked 26 Oct 2026) disallows only /wp-json/ and ?rest_route=.

_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTH = "|".join(_MONTHS)
_HEADING_DATE = re.compile(
    rf"\b(\d{{1,2}})\s+({_MONTH})(?:\s+(\d{{4}}))?\b", re.IGNORECASE
)
# "...-Council-Meeting-21-October-2025-1.pdf", "...-12-February-20251.pdf"
_FILE_DATE = re.compile(rf"(?<!\d)(\d{{1,2}})-({_MONTH})-(\d{{4}})", re.IGNORECASE)
_SECTION_YEAR = re.compile(r"\b(20\d\d)\s*$")
_LABEL = re.compile(r"^(?:(?:un)?confirmed\s+)?(agenda|minutes)$", re.IGNORECASE)
_DASHES = re.compile(r"\s*[–—-]\s*")


def _date(day: str, month: str, year: str) -> Optional[datetime.date]:
    try:
        return datetime.date(int(year), _MONTHS.index(month.lower()) + 1, int(day))
    except ValueError:
        return None


def _file_date(url: str) -> Optional[datetime.date]:
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    match = _FILE_DATE.search(name)
    return _date(*match.groups()) if match else None


def _meeting_name(heading: str, date_text: str) -> str:
    name = _DASHES.sub(" ", heading.replace(date_text, " ")).strip()
    name = re.sub(r"\s+", " ", name)
    lowered = name.lower()
    # One block calls it "Finance and Planning Meeting Committee Meeting".
    if "finance and planning" in lowered:
        prefix = "Additional " if "additional" in lowered else ""
        return f"{prefix}Finance and Planning Committee Meeting"
    return name


class _Meeting:
    def __init__(self, date: datetime.date, name: str):
        self.date = date
        self.name = name
        self.papers: dict[str, Optional[str]] = {"agenda": None, "minutes": None}


@register_scraper
class BenallaScraper(BaseScraper):
    extra_ca_certs = ("RapidSSLTLSRSACAG1.pem",)

    def __init__(self):
        super().__init__("benalla", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _blocks(self, soup: BeautifulSoup) -> list[tuple[Optional[int], Tag]]:
        """Each download block with the year of the section it sits in."""
        blocks = soup.select("div.nn-block-download")
        if not blocks:
            raise ValueError(
                f"{self.council_name}: no meeting blocks on {_LISTING_URL}"
            )
        out = []
        for block in blocks:
            section = block.find_previous(["h2", "h3"])
            match = (
                _SECTION_YEAR.search(section.get_text(" ", strip=True))
                if section
                else None
            )
            out.append((int(match[1]) if match else None, block))
        return out

    def _meeting(self, section_year: Optional[int], block: Tag) -> Optional[_Meeting]:
        heading = block.find("h4")
        text = heading.get_text(" ", strip=True) if heading else ""
        match = _HEADING_DATE.search(text)
        if not match:
            self.logger.warning(f"{self.council_name}: undated block {text!r}")
            return None
        day, month, year = match.groups()
        if year or section_year:
            date = _date(day, month, year or str(section_year))
        else:
            date = self._date_without_year(block, day, month)
        if date is None:
            self.logger.warning(f"{self.council_name}: no year for block {text!r}")
            return None
        return _Meeting(date, _meeting_name(text, match[0]))

    def _date_without_year(
        self, block: Tag, day: str, month: str
    ) -> Optional[datetime.date]:
        """Date for a block whose heading and section both lack a year."""
        for _, url in self._rows(block):
            filed = _file_date(url)
            if filed and (filed.day, filed.month) == (
                int(day),
                _MONTHS.index(month.lower()) + 1,
            ):
                return filed
        # Only "Current meeting cycle" lacks a year, and it holds the next
        # meeting, so take the year that puts it nearest today.
        today = clock.today()
        candidates = [
            d
            for y in (today.year - 1, today.year, today.year + 1)
            if (d := _date(day, month, str(y))) is not None
        ]
        return min(candidates, key=lambda d: abs(d - today), default=None)

    @staticmethod
    def _rows(block: Tag) -> list[tuple[str, str]]:
        """(paper kind, url) for each Agenda or Minutes row with a link."""
        rows = []
        for label in block.select("span.text-14"):
            match = _LABEL.match(label.get_text(" ", strip=True))
            row = label.find_parent("div", class_="rounded-8")
            link = row.find("a", href=True) if row else None
            if not match or not link:
                continue
            href = urljoin(_LISTING_URL, link["href"])
            if href.lower().endswith(".pdf"):
                rows.append((match[1].lower(), href))
        return rows

    def scraper(self) -> list[ScraperReturn]:
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser"
        )

        meetings: list[_Meeting] = []
        misfiled: list[tuple[_Meeting, str, str, datetime.date]] = []
        for section_year, block in self._blocks(soup):
            meeting = self._meeting(section_year, block)
            if meeting is None:
                continue
            meetings.append(meeting)
            for kind, url in self._rows(block):
                filed = _file_date(url)
                if filed and filed != meeting.date:
                    misfiled.append((meeting, kind, url, filed))
                elif meeting.papers[kind] is None:
                    meeting.papers[kind] = url

        for source, kind, url, filed in misfiled:
            targets = [
                m for m in meetings if m.date == filed and m.papers[kind] is None
            ]
            if len(targets) == 1:
                targets[0].papers[kind] = url
                self.logger.info(
                    f"{self.council_name}: {url} filed under {source.date} "
                    f"{source.name}; moved to {filed} {targets[0].name}"
                )
            elif (
                not any(m.date == filed for m in meetings)
                and source.papers[kind] is None
            ):
                # No meeting on the file's date, so the date in the name is
                # stale rather than the paper misfiled.
                source.papers[kind] = url
                self.logger.warning(
                    f"{self.council_name}: {url} filed under {source.date} "
                    f"{source.name} names {filed}, which has no meeting; kept"
                )
            else:
                self.logger.warning(
                    f"{self.council_name}: {url} filed under {source.date} "
                    f"{source.name} names {filed}; left out"
                )

        if not meetings:
            raise ValueError(
                f"{self.council_name}: no dated meetings on {_LISTING_URL}"
            )

        wanted = self._wanted_years()
        results = []
        for meeting in meetings:
            if meeting.date.year not in wanted:
                continue
            agenda, minutes = meeting.papers["agenda"], meeting.papers["minutes"]
            if not agenda and not minutes:
                self.logger.info(
                    f"{self.council_name}: {meeting.date} {meeting.name} has no papers"
                )
                continue
            results.append(
                ScraperReturn(
                    name=meeting.name,
                    date=meeting.date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda,
                    minutes_url=minutes,
                    download_url=agenda or minutes,
                )
            )

        if not results:
            today = clock.today()
            if wanted == {today.year} and today.month <= 3:
                # Early in a year the page may not list the new year's first
                # meeting yet.
                self.logger.warning(
                    f"{self.council_name}: no {today.year} meetings listed yet"
                )
                return []
            raise ValueError(
                f"{self.council_name}: no meetings with papers in {sorted(wanted)}"
            )
        return results
