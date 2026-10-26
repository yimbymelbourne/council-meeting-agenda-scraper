import datetime
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.kingborough.tas.gov.au"
_MEETINGS_URL = f"{_BASE_URL}/council/council-meetings/"
_ARCHIVE_URL = f"{_BASE_URL}/council/council-meetings/meetings-archive/"

# Kingborough runs an older Ionata theme than Clarence, Glenorchy and Sorell
# (see aus_council_scrapers/ionata.py), and it shares none of their filter
# form: the archive ignores `f_year`. Meetings are boxes of day/month/year
# spans with "Agenda", "Minutes" and "Audio" buttons, in two places:
#
#   /council/council-meetings/   the current schedule—about a year back plus
#                                every meeting still to come, the future ones
#                                as empty boxes until their agenda is up
#   /meetings-archive/page/N/    twelve a page, newest first, to December 2019
#
# The two overlap for the past year, so meetings are keyed by date.
#
# The boxes carry no meeting type, and neither do the filenames, except the
# AGM's ("AGM-Agenda-6.12.2025.pdf").
_AGM = re.compile(r"\bagm\b|annual[-\s]general", re.IGNORECASE)

# Special meetings are told apart by when they fall. Ordinary meetings are on
# Mondays, a fortnight apart. When the Monday is a public holiday (Easter
# Monday, Eight Hours Day, Regatta Day, the sovereign's birthday) the meeting
# moves to the Tuesday or Wednesday after. A moved ordinary meeting takes the
# place of a Monday one, so the Monday meetings either side of it are three or
# four weeks apart. A special meeting is an extra one, so the fortnightly
# Mondays either side of it are still there. Four meetings from 2020 on fit
# that: 15 June 2021, 11 August 2021, 14 June 2022 and 13 June 2023. Each
# agenda calls it a Special Meeting of the Council. The other eight non-Monday
# meetings, other than AGMs, are each "an Ordinary meeting". A special meeting
# held on a Monday cannot be told apart, and is named Council Meeting.
_ORDINARY_GAP = datetime.timedelta(days=14)

_AGENDA_LABEL = re.compile(r"^\s*agenda\s*$", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"^\s*minutes\s*$", re.IGNORECASE)

# When an agenda is too large for one file the Agenda button points at a page
# listing its parts, often beside reports tabled with it ("LCZ Review and
# Findings Report", a flood study's appendices). The agenda is the link that
# says so, or failing that its first part—Part A runs from the start of the
# agenda, so it carries the order of business.
_AGENDA_DOCUMENT = re.compile(r"agenda|\bpart[\s-]*(a|1)\b", re.IGNORECASE)


def _is_pdf(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


@register_scraper
class KingboroughScraper(BaseScraper):
    def __init__(self):
        super().__init__("kingborough", "TAS", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _is_special(meeting_date: datetime.date, mondays: list) -> bool:
        """Whether a meeting falls between two fortnightly Monday meetings."""
        if meeting_date.weekday() == 0:
            return False
        before = [d for d in mondays if d < meeting_date]
        after = [d for d in mondays if d > meeting_date]
        # With a neighbour missing (the edge of what was fetched) there is
        # nothing to go on, so the meeting stays ordinary.
        if not before or not after:
            return False
        return after[0] - before[-1] <= _ORDINARY_GAP

    def _agenda_from_page(self, page_url: str) -> Optional[str]:
        html = self.fetcher.fetch_with_requests(page_url)
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find("main") or soup.find("article") or soup.body or soup
        for link in content.find_all("a", href=True):
            url = urljoin(page_url, link["href"])
            if not _is_pdf(url):
                continue
            filename = urlparse(url).path.rsplit("/", 1)[-1]
            if _AGENDA_DOCUMENT.search(link.get_text(" ", strip=True)) or (
                _AGENDA_DOCUMENT.search(filename)
            ):
                return url
        self.logger.warning(
            f"{self.council_name}: agenda page {page_url} has no agenda PDF on it"
        )
        return None

    def _boxes(self, soup: BeautifulSoup) -> list[tuple]:
        """(date, links) for every meeting box on a page, in page order."""
        boxes = []
        for date_box in soup.select(".box-meeting-date"):
            parts = [
                date_box.select_one(f".box-meeting-{p}") for p in ("day", "month", "year")
            ]
            if any(p is None for p in parts):
                continue
            text = " ".join(p.get_text(strip=True) for p in parts)
            try:
                meeting_date = parse_date(text, dayfirst=True).date()
            except (ValueError, OverflowError):
                self.logger.warning(f"{self.council_name}: unparseable date {text!r}")
                continue
            box = date_box.find_parent(class_="box-inner") or date_box.parent
            boxes.append((meeting_date, box.find_all("a", href=True)))
        return boxes

    def _record(self, meeting_date, links: list[Tag], page_url: str):
        agenda_url = minutes_url = None
        for link in links:
            label = link.get_text(" ", strip=True)
            url = urljoin(page_url, link["href"].strip())
            if _AGENDA_LABEL.match(label) and agenda_url is None:
                # Labels are reliable even where filenames are not: the 6 July
                # 2026 minutes are "No.-12-6-July-2026-Public-Copy.pdf".
                agenda_url = url if _is_pdf(url) else self._agenda_from_page(url)
            elif _MINUTES_LABEL.match(label) and minutes_url is None:
                minutes_url = url if _is_pdf(url) else None
                if minutes_url is None:
                    self.logger.warning(
                        f"{self.council_name}: minutes for {meeting_date} link to "
                        f"{url}, not a PDF; left out"
                    )
        if not agenda_url and not minutes_url:
            return None

        filenames = " ".join(
            urlparse(u).path.rsplit("/", 1)[-1] for u in (agenda_url, minutes_url) if u
        )
        return ScraperReturn(
            name="Annual General Meeting" if _AGM.search(filenames) else "Council Meeting",
            date=meeting_date.isoformat(),
            time=None,
            webpage_url=page_url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        earliest = min(wanted)
        by_date: dict = {}

        # Every box's date, whatever its year and whether or not it has
        # documents yet, for telling special meetings apart (see
        # `_ORDINARY_GAP`).
        all_dates: set = set()

        def take(page_url: str, boxes: list[tuple]) -> None:
            for meeting_date, links in boxes:
                all_dates.add(meeting_date)
                if meeting_date.year not in wanted or meeting_date in by_date:
                    continue
                record = self._record(meeting_date, links, page_url)
                if record is not None:
                    by_date[meeting_date] = record

        # The schedule page is the only place an upcoming meeting appears, and
        # it reaches back about a year, so it is needed whenever the current
        # year or later is wanted.
        if max(wanted) >= clock.current_year():
            soup = BeautifulSoup(
                self.fetcher.fetch_with_requests(_MEETINGS_URL), "html.parser"
            )
            take(_MEETINGS_URL, self._boxes(soup))

        url: Optional[str] = _ARCHIVE_URL
        while url:
            soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
            boxes = self._boxes(soup)
            take(url, boxes)
            if not boxes or boxes[-1][0].year < earliest:
                # Newest first, so once a page ends before the earliest year
                # wanted, every later page is older still.
                break
            next_link = soup.select_one("a.next[href]")
            url = urljoin(url, next_link["href"]) if next_link else None

        mondays = sorted(d for d in all_dates if d.weekday() == 0)
        for meeting_date, record in by_date.items():
            if record.name == "Council Meeting" and self._is_special(meeting_date, mondays):
                record.name = "Special Council Meeting"

        results = sorted(by_date.values(), key=lambda r: r.date, reverse=True)
        if not results:
            self.logger.warning(
                f"{self.council_name}: no meetings with documents found for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
