import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date
from requests.utils import requote_uri

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://perth.wa.gov.au"
_LANDING_URL = "https://perth.wa.gov.au/council/council-meetings"

# The City of Perth (Sitecore) publishes meetings in two shapes, and a
# scraper has to read both:
#
# * Past years each have a page—"2025 Council Meetings" and so on—holding
#   a Date | Time | Meeting | Details table whose Details cell links the
#   documents directly. The table is paged 20 rows at a time with
#   `?Meetings=N`, followed through the pager's "Next" link.
# * The current year has no such page yet (`/2026-council-meetings` is a 404
#   page). It sits on the landing page instead, as the same table shape split
#   across "Upcoming meetings" and "Past meetings" tabs, but the Details cell
#   only says "Agenda & Minutes" and links the meeting's own page. The
#   documents are on that page alone, so the current year costs a request per
#   meeting.
#
# When a year closes it presumably moves to a year page of its own; the
# landing page links those by label, and the slugs are irregular
# (`2017-meetings`, `2018-council-meetings`), so they are read off the label.
_YEAR_LINK = re.compile(r"^\s*(\d{4})\s+Council Meetings\s*$", re.IGNORECASE)

# The per-meeting pages are fetched only for these meeting types. Perth holds
# about 40 meetings a year, most of them briefing sessions and committees
# (audit, CEO performance review, policy and legislation), and at the
# fetcher's 2 s per-host spacing a page each would cost well over a minute of
# the nightly run's shared budget. Council meetings carry the decisions; the
# development and design panels are the planning bodies; the electors' general
# meeting is a meeting of the council with its electors, once a year. Year
# pages list every meeting type at no extra cost, so this applies to the
# current year only.
#
# What this leaves out, knowingly: the agenda briefing sessions, which are
# where the next council meeting's reports are first published (each has its
# own agenda, out while the Ordinary Council Meeting's is still "Not yet
# published"), and the committees. The briefings would be about 11 more
# requests a year.
_FETCH_MEETING_PAGE = re.compile(
    r"council meeting|development assessment|planning|design advisory|electors",
    re.IGNORECASE,
)

# A meeting's Details cell (year pages) or Documents list (meeting pages)
# mixes the agenda and minutes with notes, audio, a "Table of Report Changes",
# public question registers, attachments, reports under separate cover,
# late and urgent items, and notices of amendment. Only the first two are
# the meeting's agenda and minutes.
_AGENDA_LABEL = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"\bminutes\b", re.IGNORECASE)
_NOT_THE_PAPERS = re.compile(
    r"attachment|separate cover|supplementar|late item|additional|amend"
    r"|notice|urgent|register|table of report|presentation|form\b|revised"
    r"|updated|response|\bitem\b",
    re.IGNORECASE,
)

# Meeting names in the tables are hand-typed, and some carry a date fragment
# or a cancellation marker: "Special Council Meeting 17 Sep", "Design Advisory
# Committee Nov 2021", "Design Advisory Committee (CANCELLED)".
_CANCELLED = re.compile(r"[\s\-–(]*cancelled\)?\s*$", re.IGNORECASE)
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
# A month needs a day or a year beside it, so a name that merely ends in a
# month-like word is left alone.
_TRAILING_DATE = re.compile(
    rf"\s+(?:\d{{1,2}}\s+{_MONTH}(?:\s+\d{{2,4}})?|{_MONTH}\s+\d{{4}})\s*$",
    re.IGNORECASE,
)

# Never follow the pager further than this per year. A year holds 30-50
# meetings, three pages at most, so this only stops a pager that loops.
_MAX_PAGES = 10


@register_scraper
class PerthScraper(BaseScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 26 s (14
    # requests: the landing page and 13 meeting pages). Orders dispatch only
    # (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 26

    def __init__(self):
        council = "perth"
        state = "WA"
        base_url = _BASE_URL
        super().__init__(council, state, base_url)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _year_pages(soup: BeautifulSoup) -> dict[int, str]:
        pages: dict[int, str] = {}
        for link in soup.find_all("a", href=True):
            match = _YEAR_LINK.match(link.get_text(" ", strip=True))
            if match:
                pages.setdefault(
                    int(match.group(1)), urljoin(_LANDING_URL, link["href"])
                )
        return pages

    @staticmethod
    def _clean_name(name: str) -> str:
        name = re.sub(r"\s+", " ", name).strip()
        name = _CANCELLED.sub("", name).strip()
        return _TRAILING_DATE.sub("", name).strip()

    @staticmethod
    def _clean_time(text: str) -> Optional[str]:
        match = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)", text or "", re.IGNORECASE)
        if not match:
            return None
        return f"{int(match.group(1))}:{match.group(2)} {match.group(3).upper()}"

    @staticmethod
    def _papers(links, page_url: str) -> tuple[Optional[str], Optional[str]]:
        """Pick the agenda and minutes out of a meeting's document links.

        The label is the link text, falling back to its title. A plain
        "Agenda" or "Minutes" wins over a longer label, and confirmed minutes
        over the unconfirmed set when a meeting lists both.
        """
        agenda = minutes = None
        agenda_rank = minutes_rank = 99
        for link in links:
            href = urljoin(page_url, link["href"])
            if not href.lower().split("?")[0].endswith(".pdf"):
                continue
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True)) or (
                link.get("title") or ""
            )
            if _NOT_THE_PAPERS.search(label):
                continue
            if _MINUTES_LABEL.search(label):
                rank = (
                    0
                    if re.search(r"(?<!un)confirmed", label, re.IGNORECASE)
                    else (1 if label.lower() == "minutes" else 2)
                )
                if rank < minutes_rank:
                    minutes, minutes_rank = href, rank
            elif _AGENDA_LABEL.search(label):
                rank = 0 if label.lower() == "agenda" else 1
                if rank < agenda_rank:
                    agenda, agenda_rank = href, rank
        return agenda, minutes

    @staticmethod
    def _row_date(text: str) -> Optional[datetime.date]:
        text = text.strip()
        # "19 Oct 26": a two-digit year, which dateutil would also read, but
        # strptime says exactly what the format is.
        for fmt in ("%d %b %y", "%d %b %Y"):
            try:
                return datetime.datetime.strptime(text, fmt).date()
            except ValueError:
                pass
        try:
            return parse_date(text, dayfirst=True).date()
        except (ValueError, OverflowError):
            return None

    def _rows(self, soup: BeautifulSoup, page_url: str):
        """Yield (date, time, name, meeting page URL, details cell) per row."""
        for table in soup.select("div.page-table table"):
            body = table.find("tbody") or table
            for row in body.find_all("tr"):
                cells = row.find_all("td", recursive=False)
                if len(cells) < 4:
                    continue
                date = self._row_date(cells[0].get_text(" ", strip=True))
                if date is None:
                    continue
                link = cells[2].find("a", href=True)
                name = (link or cells[2]).get_text(" ", strip=True)
                # Some hrefs carry raw spaces ("/council-meetings/Special
                # Council Meeting 17 Sep"); the server takes them encoded, and
                # a stored URL has to be a valid one.
                meeting_url = (
                    requote_uri(urljoin(page_url, link["href"])) if link else None
                )
                yield (
                    date,
                    self._clean_time(cells[1].get_text(" ", strip=True)),
                    self._clean_name(name),
                    meeting_url,
                    cells[3],
                )

    def _year_page_meetings(self, year: int, url: str) -> list[ScraperReturn]:
        results = []
        seen_pages = set()
        page_url = url
        while page_url and page_url not in seen_pages and len(seen_pages) < _MAX_PAGES:
            seen_pages.add(page_url)
            soup = BeautifulSoup(
                self.fetcher.fetch_with_requests(page_url), "html.parser"
            )
            for date, time, name, meeting_url, details in self._rows(soup, page_url):
                if date.year != year:
                    continue
                agenda_url, minutes_url = self._papers(
                    details.find_all("a", href=True), page_url
                )
                if not agenda_url and not minutes_url:
                    continue
                results.append(
                    ScraperReturn(
                        name=name,
                        date=date.isoformat(),
                        time=time,
                        webpage_url=meeting_url or page_url,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )

            next_link = None
            for link in soup.select("div.page-selector a[href]"):
                if link.get_text(strip=True).lower() == "next":
                    next_link = urljoin(page_url, link["href"])
            page_url = next_link
        return results

    def _meeting_page(self, date, time, name, url) -> Optional[ScraperReturn]:
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        documents = soup.select_one("div.document-list")
        if documents is None:
            return None
        agenda_url, minutes_url = self._papers(documents.find_all("a", href=True), url)
        if not agenda_url and not minutes_url:
            return None

        location = None
        venue = soup.select_one("div.field-meetinglocation")
        if venue:
            label = venue.find("span")
            if label:
                label.extract()
            location = re.sub(r"\s+", " ", venue.get_text(" ", strip=True)) or None

        return ScraperReturn(
            name=name,
            date=date.isoformat(),
            time=time,
            webpage_url=url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
            location=location,
        )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        landing = BeautifulSoup(
            self.fetcher.fetch_with_requests(_LANDING_URL), "html.parser"
        )
        year_pages = self._year_pages(landing)

        results: list[ScraperReturn] = []
        # A page that cannot be fetched is logged and skipped, so one bad page
        # does not cost the rest. But if nothing at all comes back and a fetch
        # failed, that failure is the answer, and it is raised: returning []
        # would report a blocked or down site as a council with no meetings.
        last_error: Optional[Exception] = None
        for year in sorted(wanted & set(year_pages)):
            try:
                results.extend(self._year_page_meetings(year, year_pages[year]))
            except Exception as e:
                last_error = e
                self.logger.warning(f"Could not read the {year} meetings page: {e}")

        # The landing page's own tables: the current year, plus upcoming
        # meetings. Anything already read off a year page is not fetched twice.
        known = {r.webpage_url for r in results}
        skipped = 0
        for date, time, name, meeting_url, details in self._rows(landing, _LANDING_URL):
            if date.year not in wanted or (meeting_url and meeting_url in known):
                continue
            links = details.find_all("a", href=True)
            agenda_url, minutes_url = self._papers(links, _LANDING_URL)
            if agenda_url or minutes_url:
                meeting = ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=time,
                    webpage_url=meeting_url or _LANDING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            elif not links or not meeting_url:
                # "Not yet published".
                continue
            elif not _FETCH_MEETING_PAGE.search(name):
                skipped += 1
                continue
            else:
                try:
                    meeting = self._meeting_page(date, time, name, meeting_url)
                except Exception as e:
                    last_error = e
                    self.logger.warning(f"Could not read {meeting_url}: {e}")
                    continue
            if meeting:
                known.add(meeting_url)
                results.append(meeting)

        if skipped:
            self.logger.info(
                f"{skipped} briefing/committee meeting page(s) not fetched "
                f"(outside the per-meeting allowlist)"
            )
        if not results and last_error is not None:
            raise last_error
        if not results:
            self.logger.warning(f"{self.council_name} scraper found no meetings")
        else:
            self.logger.info(
                f"{self.council_name} scraper found {len(results)} meetings"
            )
        return results
