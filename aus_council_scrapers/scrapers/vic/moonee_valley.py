"""Moonee Valley publishes its meetings across two systems.

From 2026 everything is on docspublished (slug "MVCC"), which
`DocsPublishedScraper` reads without a browser. Everything before that—
2018 to 2025—is a single WordPress page on mvcc.vic.gov.au: year accordions
of tables with Date | Agendas and attachments | Minutes | Watch columns, one
set for Council meetings and another for committees.

That page sits behind Imperva Incapsula, which answers any requests client
with a 212-byte JavaScript challenge, so it needs Selenium. Headless Chrome
passed it every time it was tried while this was built (from a home IP; never
from a GitHub runner, where Imperva may score the address harder). It
costs nothing in production, though: the archive ends in 2025 and production
asks for the current year, so `years_filter` keeps the browser from starting.
Only a full-history run, such as recording the cassette, loads it.

The archive is hand-edited and inconsistent in ways that matter:

- Dates in most years omit the year ("Tuesday, 9 December - 6:30pm"), so it
  comes from the accordion heading.
- The agenda cell holds the agenda followed by per-item attachments, so only
  the link labelled or named as the agenda is taken.
- A few links point at the wrong meeting: 26 March 2019's "Agenda" is the 12
  March agenda, and 27 February 2018's is that meeting's minutes. A link
  whose filename names another day, or the other document kind, is dropped
  rather than filed against this meeting.
- One row is dated wrongly instead. The 2021 "Place Naming Delegated
  Committee - Tuesday 16 March 2021" row links Agenda-23-March-2021.pdf and
  Minutes-23-March-2021.pdf, whose first pages both read "Tuesday 23 March
  2021". When a row's agenda and minutes filenames agree on a day the row
  does not name, the papers are believed and the meeting goes on their day.
"""

import re
import urllib.parse
from typing import Optional

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from aus_council_scrapers import clock
from aus_council_scrapers.base import (
    DocsPublishedScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.constants import EARLIEST_YEAR

ARCHIVE_URL = "https://mvcc.vic.gov.au/my-council/council-meetings/"

# The last year the WordPress archive holds; docspublished starts the year
# after.
ARCHIVE_LAST_YEAR = 2025

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October"
    "|November|December"
)
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})\s+({_MONTHS})\b(?:\s+(20\d\d))?", re.I)
# Dates as they appear in the archive's filenames: "12-March-2019".
_FILE_DAY_MONTH = re.compile(rf"(?<!\d)(\d{{1,2}})-({_MONTHS})\b", re.I)
_TIME = re.compile(r"\b\d{1,2}(?:[.:]\d{2})?\s*[ap]\.?m\b", re.I)


@register_scraper
class MooneeValleyScraper(DocsPublishedScraper):
    publishing_slug = "mvcc"

    # No `strip_headless_user_agent`. Incapsula refused plain headless Chrome
    # once when the platform was scouted, but run both ways when this was
    # built it made no difference—198 archive meetings each way, twice—and
    # the flag is opt-in only where it is shown to matter. If the archive
    # starts coming back as an Incapsula incident page, try it first.

    def __init__(self):
        super().__init__("moonee_valley", "VIC")

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        results = []

        if max(wanted) > ARCHIVE_LAST_YEAR:
            # docspublished lists meetings before their papers are out; the
            # base class skips those, so only published meetings arrive.
            results.extend(super().scraper())

        if min(wanted) <= ARCHIVE_LAST_YEAR:
            archive = self._scrape_archive()
            # Unfiltered, keep the whole page as the base class keeps the
            # whole document list: it was one load either way.
            if getattr(self, "years_filter", None):
                archive = [m for m in archive if m.cleaned_date.year in wanted]
            results.extend(archive)

        if not results:
            self.logger.warning(f"{self.council_name} scraper found no meetings")
        return results

    # ------------------------------------------------------------------
    # The 2018–2025 WordPress archive
    # ------------------------------------------------------------------

    def _scrape_archive(self) -> list[ScraperReturn]:
        try:
            html = self.fetcher.fetch_with_selenium(
                ARCHIVE_URL,
                wait_time=30,
                wait_condition=EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.fl-accordion-item table")
                ),
            )
        except Exception as error:
            self.logger.warning(
                f"Could not load the 2018-2025 archive at {ARCHIVE_URL} "
                f"(Incapsula?): {type(error).__name__}: {error}"
            )
            return []

        soup = BeautifulSoup(html, "html.parser")
        results: list[ScraperReturn] = []
        seen = set()

        for item in soup.select("div.fl-accordion-item"):
            label = item.select_one(".fl-accordion-button-label")
            year_match = re.fullmatch(
                r"\s*(20\d\d)\s*", label.get_text(" ") if label else ""
            )
            if not year_match:
                continue  # the page's other accordions: "Security", "Privacy"...
            year = int(year_match.group(1))

            section = item.find_previous("h2")
            committees = bool(section and "committee" in section.get_text(" ").lower())

            # Tables are sometimes introduced by their own h3—in 2018 the
            # Development Assessment Panel and two special committees each
            # have one—so walk headings and tables in document order.
            heading = None
            for element in item.find_all(["h3", "table"]):
                if element.name == "h3":
                    heading = " ".join(element.get_text(" ").split())
                    continue
                for meeting in self._parse_table(element, year, committees, heading):
                    key = (
                        meeting.name,
                        meeting.date,
                        meeting.agenda_url,
                        meeting.minutes_url,
                    )
                    if key not in seen:
                        seen.add(key)
                        results.append(meeting)

        if not results:
            self.logger.warning(
                f"The archive at {ARCHIVE_URL} loaded but no meetings were "
                f"parsed from it—the page layout may have changed"
            )
        return results

    def _parse_table(
        self, table, year: int, committees: bool, heading: Optional[str]
    ) -> list[ScraperReturn]:
        meetings = []
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue  # header row

            when = " ".join(cells[0].get_text(" ").split())
            date = self._date(when, year)
            if date is None:
                continue

            minutes_cell = cells[2] if len(cells) > 2 else None
            agenda_url, minutes_url = self._papers(cells[1], minutes_cell, date)
            if not agenda_url and not minutes_url:
                papers_date = self._papers_date(cells[1], minutes_cell, date)
                if papers_date:
                    self.logger.info(
                        f"Row dated {date} carries papers for {papers_date}; "
                        f"recording it on {papers_date}"
                    )
                    date = papers_date
                    agenda_url, minutes_url = self._papers(cells[1], minutes_cell, date)
            if not agenda_url and not minutes_url:
                continue  # "This meeting was cancelled.", "Confidential"

            time_match = _TIME.search(when)
            meetings.append(
                ScraperReturn(
                    name=self._name(when, agenda_url, committees, heading),
                    date=date.isoformat(),
                    time=time_match.group() if time_match else None,
                    webpage_url=ARCHIVE_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return meetings

    @staticmethod
    def _date(text: str, year: int):
        match = _DAY_MONTH.search(text)
        if not match:
            return None
        day, month, explicit_year = match.groups()
        try:
            return parse_date(f"{day} {month} {explicit_year or year}").date()
        except ValueError:
            return None

    def _papers(self, agenda_cell, minutes_cell, date):
        """This meeting's (agenda, minutes) links from a row's two cells."""
        agenda_url = self._pick(agenda_cell, "agenda", date)
        minutes_url = (
            self._pick(minutes_cell, "minutes", date, last=True)
            if minutes_cell is not None
            else None
        )
        return agenda_url, minutes_url

    def _papers_date(self, agenda_cell, minutes_cell, date):
        """The day a row's papers are for, when it is not the row's own day.

        Only trusted when the agenda and the minutes both name that day in
        their filenames. One misfiled link alone—26 March 2019's agenda is
        really 12 March's—says nothing about when the meeting was, and that
        row still has its own minutes, so it never gets here.
        """
        if minutes_cell is None:
            return None
        days = set()
        for cell, kind, last in (
            (agenda_cell, "agenda", False),
            (minutes_cell, "minutes", True),
        ):
            href = self._pick(cell, kind, None, last=last)
            day = self._file_day(href) if href else None
            if day is None:
                return None
            days.add(day)
        if len(days) != 1:
            return None
        ((day, month),) = days
        try:
            papers_date = date.replace(month=month, day=day)
        except ValueError:
            return None
        return papers_date if papers_date != date else None

    @staticmethod
    def _file_day(href: str) -> Optional[tuple[int, int]]:
        """(day, month) named in a link's filename, if any."""
        filename = urllib.parse.urlparse(href).path.rsplit("/", 1)[-1]
        match = _FILE_DAY_MONTH.search(filename)
        if not match:
            return None
        day, month = match.groups()
        return int(day), parse_date(month).month

    def _pick(self, cell, kind: str, date, last: bool = False) -> Optional[str]:
        """The one link in a cell that is this meeting's agenda or minutes.

        A link qualifies when its filename does not say it is the other kind
        or an attachment, and any date in its filename is this meeting's day
        (`date` None skips that check). The filename year is not compared:
        30 January 2020's agenda is filed as "...30-January-2019".

        Links labelled as `kind` ("Agenda", "Minutes", "Updated Minutes")
        win. A link that is only named as `kind` is a fallback for a cell
        with no labelled one—30 January 2020's agenda is labelled "Special
        Council Meeting - Newmarket Trees"—because a cell's attachments can
        carry the word too: 10 September 2024's minutes cell ends with the
        Audit and Risk Committee's "...Confirmed-Minutes.pdf". When several
        qualify the first is taken, or the last for minutes, where a later
        labelled link is the "Updated Minutes".
        """
        other = "minutes" if kind == "agenda" else "agenda"
        labelled, named = [], []
        for link in cell.find_all("a", href=True):
            href = urllib.parse.urljoin(ARCHIVE_URL, link["href"])
            path = urllib.parse.urlparse(href).path
            if not path.lower().endswith(".pdf"):
                continue
            filename = path.rsplit("/", 1)[-1].lower()
            label = link.get_text(" ", strip=True).lower()

            if label.startswith(kind):
                bucket = labelled
            elif kind in filename:
                bucket = named
            else:
                continue
            if other in filename or re.search(r"attach|appendi", filename):
                continue

            file_day = self._file_day(href)
            if date is not None and file_day and file_day != (date.day, date.month):
                self.logger.info(
                    f"Skipping {kind} link for {date}: {filename} names " f"another day"
                )
                continue

            bucket.append(href)

        candidates = labelled or named
        if not candidates:
            return None
        return candidates[-1] if last else candidates[0]

    @staticmethod
    def _name(
        when: str, agenda_url: Optional[str], committees: bool, heading: Optional[str]
    ) -> str:
        if committees:
            # "Neighbourhood Spirit Delegated Committee Meeting - Thursday,
            # 4 May - 6pm": the body is everything before the first dash.
            name = re.split(r"\s+[-–]\s*|[-–]\s+", when, maxsplit=1)[0]
            if name.lower().startswith("hearing of submissions"):
                return "Hearing of Submissions"
            return name

        if heading and not re.match(r"20\d\d\b", heading):
            # "Budget Submissions Committee Meeting - 5 June 2018"
            return re.split(r"\s+[-–]\s+", heading, maxsplit=1)[0]

        # The date cell and the agenda's own filename, not the whole agenda
        # cell: its attachment titles mention things like the "Moonee Ponds
        # Special Rate and Charge", which would make any meeting "Special".
        text = f"{when} {agenda_url or ''}".lower()
        if "elect the mayor" in text or "election of mayor" in text:
            return "Election of Mayor and Deputy Mayor"
        if "special" in text:
            return "Special Council Meeting"
        if "statutory" in text:
            return "Statutory Council Meeting"
        return "Council Meeting"
