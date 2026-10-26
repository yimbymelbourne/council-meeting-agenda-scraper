import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.narromine.nsw.gov.au"
_CURRENT_URL = f"{_BASE_URL}/council/council-meetings"
_PREVIOUS_URL = f"{_BASE_URL}/council/previous-years-council-meetings"

# Narromine lists meetings as an accordion, one item per month ("2026
# February"): the current year on the council-meetings page, 2024 and 2025 on
# the previous-years page. Nothing older is online.
#
# A meeting's business paper is split into numbered PDFs: "00. Minutes
# 11.02.26", "01. Meeting Notice and Agenda - February 2026", then "02.
# Mayoral Minute", "05. Reports to Council - General Manager" and so on. The
# "01" notice-and-agenda is emitted as the agenda: it is the agenda proper,
# the order of business. The reports it lists are in the 02-11 files beside
# it, and there is no single file holding them all.
#
# A month with an extraordinary meeting as well holds two such runs, each
# headed in bold ("Extraordinary Council Meeting 20 May 2025") or simply
# restarting at "00."/"01.".
_ITEM_TITLE = re.compile(r"^\s*(\d{4})\s+([A-Za-z]+)\s*$")
_NUMBERED = re.compile(r"^\s*(\d{1,2})[a-z]?\.\s*")
# "00. Minutes", "00. MInutes"; not "02. Mayoral Minute".
_MINUTES = re.compile(r"^\s*\d{1,2}[a-z]?\.\s*minutes\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_SUPPLEMENTARY = re.compile(r"supplementary|late|addendum", re.IGNORECASE)
_EXTRAORDINARY = re.compile(r"extraordinary", re.IGNORECASE)
_MEETING_HEADING = re.compile(r"\bmeeting\b", re.IGNORECASE)

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
# "20 May 2025", "8 October 2025".
_LONG_DATE = re.compile(
    r"(?<!\d)(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{4})",
    re.IGNORECASE,
)
# The minutes' labels: "Minutes 11.02.26", "Minutes 8.7.26".
_DOTTED_DATE = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})(?![\d.])")
# "The next Council Meeting will be held on Wednesday 14 October 2026."
_NEXT_MEETING = re.compile(
    r"next\s+council\s+meeting\s+will\s+be\s+held\s+on\s+(?:[A-Za-z]+,?\s+)?"
    r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    re.IGNORECASE,
)


def _long_date(text: str) -> Optional[datetime.date]:
    for day, month, year in _LONG_DATE.findall(text):
        try:
            return datetime.date(int(year), _MONTHS[month[:3].lower()], int(day))
        except ValueError:
            continue
    return None


def _dotted_date(text: str) -> Optional[datetime.date]:
    for day, month, year in _DOTTED_DATE.findall(text):
        year = int(year) + (2000 if len(year) == 2 else 0)
        try:
            return datetime.date(year, int(month), int(day))
        except ValueError:
            continue
    return None


class _Run:
    """One meeting's run of numbered documents within a month's item."""

    def __init__(self, heading: str = ""):
        self.heading = heading
        self.last_number = -1
        self.labels: list[str] = []
        self.agenda: Optional[tuple[str, str]] = None
        self.minutes: Optional[tuple[str, str]] = None


@register_scraper
class NarromineScraper(BaseScraper):
    def __init__(self):
        super().__init__("narromine", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _runs(content: Tag) -> list[_Run]:
        """Split a month's documents into meetings, in page order."""
        runs: list[_Run] = []
        for element in content.find_all(["strong", "b", "h2", "h3", "h4", "a"]):
            if element.name != "a":
                text = re.sub(r"\s+", " ", element.get_text(" ", strip=True))
                # A bold heading names the meeting the following run belongs to.
                if text and _MEETING_HEADING.search(text) and not element.find("a"):
                    runs.append(_Run(text))
                continue
            href = element.get("href")
            label = re.sub(r"\s+", " ", element.get_text(" ", strip=True))
            if not href or not label or ".pdf" not in href.lower():
                continue
            number_match = _NUMBERED.match(label)
            number = int(number_match.group(1)) if number_match else None
            # A run with no heading of its own starts where the numbering does.
            if not runs or (number is not None and number <= runs[-1].last_number):
                runs.append(_Run())
            run = runs[-1]
            if number is not None:
                run.last_number = number
            run.labels.append(label)
            url = urljoin(_BASE_URL, href)
            if _MINUTES.match(label):
                run.minutes = run.minutes or (label, url)
            elif _AGENDA.search(label) and not _SUPPLEMENTARY.search(label):
                run.agenda = run.agenda or (label, url)
        return [run for run in runs if run.agenda or run.minutes]

    def _meeting_date(
        self, run: _Run, year: int, month: int, next_meeting: Optional[datetime.date]
    ) -> Optional[datetime.date]:
        """The meeting's date, from the most specific place that gives it.

        A heading or a label naming the day ("Extraordinary Council Meeting
        20 May 2025", "Meeting Notice and Agenda - 14 February 2024") wins.
        Most ordinary meetings are dated only by their minutes ("00. Minutes
        11.02.26"), and an agenda posted before the meeting has only its
        month ("Meeting Notice and Agenda - October 2026"). For that one, the
        page's own "next Council Meeting will be held on ..." line gives the
        day, when it falls in the same month. Nothing else does, and a day
        is never guessed.
        """
        candidates = [_long_date(run.heading)]
        if run.minutes:
            candidates += [_dotted_date(run.minutes[0]), _long_date(run.minutes[0])]
        if run.agenda:
            candidates.append(_long_date(run.agenda[0]))
        for date in candidates:
            if date is None:
                continue
            if (date.year, date.month) != (year, month):
                # A label from another month means the label is wrong, not
                # the accordion it was filed under.
                self.logger.warning(
                    f"{self.council_name}: {date} filed under {year}-{month:02d}; ignored"
                )
                continue
            return date
        if (
            run.agenda
            and not run.minutes
            and next_meeting
            and (next_meeting.year, next_meeting.month) == (year, month)
            and not _EXTRAORDINARY.search(" ".join([run.heading, *run.labels]))
        ):
            return next_meeting
        return None

    def _meetings(
        self, url: str, wanted: set[int]
    ) -> tuple[list[ScraperReturn], set[int]]:
        """The wanted meetings on one page, and every year the page holds."""
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        items = soup.select("li.accordion-item")

        next_meeting = None
        match = _NEXT_MEETING.search(soup.get_text(" ", strip=True))
        if match:
            next_meeting = _long_date(match.group(1))

        results = []
        years_seen = set()
        for item in items:
            title = item.find("a", class_="accordion-title")
            content = item.find(class_="accordion-content")
            title_match = (
                _ITEM_TITLE.match(title.get_text(" ", strip=True)) if title else None
            )
            if not title_match or content is None:
                continue
            year = int(title_match.group(1))
            month = _MONTHS.get(title_match.group(2)[:3].lower())
            if month is None:
                continue
            years_seen.add(year)
            if year not in wanted:
                continue
            for run in self._runs(content):
                date = self._meeting_date(run, year, month, next_meeting)
                if date is None:
                    self.logger.warning(
                        f"{self.council_name}: no day for the {year}-{month:02d} "
                        f"meeting ({run.agenda or run.minutes}); skipped"
                    )
                    continue
                text = " ".join([run.heading, *run.labels])
                agenda_url = run.agenda[1] if run.agenda else None
                minutes_url = run.minutes[1] if run.minutes else None
                results.append(
                    ScraperReturn(
                        name=(
                            "Extraordinary Council Meeting"
                            if _EXTRAORDINARY.search(text)
                            else "Ordinary Council Meeting"
                        ),
                        date=date.isoformat(),
                        time=None,
                        webpage_url=url,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )
        if not items:
            # The accordion is the whole listing; a page without one has
            # changed shape, and reading it as empty would hide that.
            raise RuntimeError(f"{self.council_name}: no meeting accordion on {url}")
        return results, years_seen

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # The current page first. The previous-years page is read only for a
        # wanted year older than everything the current page holds, so a
        # production run (this year only) costs one request.
        results, current_years = self._meetings(_CURRENT_URL, wanted)
        if any(
            year < min(current_years, default=clock.current_year()) for year in wanted
        ):
            previous, _ = self._meetings(_PREVIOUS_URL, wanted)
            results = previous + results

        results.sort(key=lambda r: (r.date, r.name))
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
