import calendar
import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://lockhart.qld.gov.au"
_CURRENT_URL = f"{_BASE_URL}/publications/council-meetings-minutes"
_ARCHIVE_URL = f"{_CURRENT_URL}/archive"

# A TYPO3 site. The current year is on one page and every earlier year on an
# archive page, each as "<year> Meetings" headings over "Council Meeting
# <Month> <year>" blocks of links. robots.txt answers 404, so nothing is
# disallowed.
#
# The blocks and the link text give only a month, and the month is the one
# the meeting is *for*, not when it sat: the March 2026 meeting was held on
# 2 April ("LHRASC_Agenda_-_Mar__held_Apr_2_2026.pdf"), the May 2021 one on
# 16 June ("Minutes-LRASC-16th-of-June-May-Meeting-V2.pdf"). The day is read
# from the file name: the agenda's since 2025 (checked against the papers'
# own "Date:" line for May and March 2026), the minutes' before then. A
# meeting whose papers carry no day anywhere—most minutes from July 2024 to
# January 2025, several special meetings—is left out rather than given an
# invented one. Agendas are published only from 2025.

_MONTH_WORD = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
# "LHRASC_Agenda_-_May_20_2026.pdf", "..._-_Mar__held_Apr_2_2026.pdf"
_MONTH_DAY_YEAR = re.compile(
    rf"(?<![a-z]){_MONTH_WORD}[-_ ]+(\d{{1,2}})[-_ ]+(20\d\d)(?!\d)", re.IGNORECASE
)
# "Minutes-2024-04-24th-April-2024.pdf", "Minutes-24th-of-the-February-2022",
# "Minutes-September-meeting-29th-and-30th-Sept-Cairns-2020.pdf" (the first
# day of a two-day sitting), "Minutes-June-meeting-2020-held-on-15th-July".
_DAY_MONTH = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?"
    rf"(?:[-_ ]+and[-_ ]+\d{{1,2}}(?:st|nd|rd|th)?)?"
    rf"[-_ ]+(?:of[-_ ]+(?:the[-_ ]+)?)?{_MONTH_WORD}"
    rf"(?:[-_ ]+(20\d\d)(?!\d))?",
    re.IGNORECASE,
)
_HEADING_YEAR = re.compile(r"^(20\d\d) Meetings$")
_BLOCK = re.compile(rf"{_MONTH_WORD}\s+(20\d\d)\s*$", re.IGNORECASE)

_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_BUDGET = re.compile(r"\bbudget\b", re.IGNORECASE)
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)
_POST_ELECTION = re.compile(r"post[- ]quadrennial|post[- ]election", re.IGNORECASE)

_MONTHS = {m.lower()[:3]: i for i, m in enumerate(calendar.month_abbr) if m}


def _file_day(url: str, year_hint: int, month_hint: int) -> Optional[datetime.date]:
    name = url.rsplit("/", 1)[-1]
    match = _MONTH_DAY_YEAR.search(name)
    if match:
        month, day, year = (
            _MONTHS[match.group(1).lower()[:3]],
            match.group(2),
            match.group(3),
        )
    else:
        match = _DAY_MONTH.search(name)
        if not match:
            return None
        day, month, year = (
            match.group(1),
            _MONTHS[match.group(2).lower()[:3]],
            match.group(3),
        )
        if not year:
            # "...-held-on-15th-July" under June 2020: the sitting is in or
            # after the month it is for, so a month earlier than the block's
            # is the next year's.
            year = year_hint + (1 if month < month_hint - 6 else 0)
    try:
        return datetime.date(int(year), month, int(day))
    except ValueError:
        return None


# The council's first meeting of a year is late January or February (28
# January 2026, 19 February 2025), so for its first weeks the current year
# is empty. An empty year is an error only once this much of it has passed,
# the rule CraftMeetingsModuleScraper uses.
_NEW_YEAR_GRACE_DAYS = 90


def _owed_papers(year: int) -> bool:
    """Whether a year has run long enough that it must have papers."""
    today = clock.today()
    return year < today.year or (
        year == today.year
        and (today - datetime.date(year, 1, 1)).days >= _NEW_YEAR_GRACE_DAYS
    )


@register_scraper
class LockhartRiverScraper(BaseScraper):
    def __init__(self):
        super().__init__("lockhart_river", "QLD", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _meeting_type(text: str) -> str:
        if _BUDGET.search(text):
            return "Special Budget Meeting"
        if _POST_ELECTION.search(text):
            return "Post-Election Council Meeting"
        if _SPECIAL.search(text):
            return "Special Council Meeting"
        return "Ordinary Council Meeting"

    def _blocks(self, url: str) -> tuple[set[int], list[tuple]]:
        """The years on a page, and its blocks as (year, month, [(text, href)])."""
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        years, blocks = set(), []
        year = None
        for element in soup.find_all(["h2", "h4", "a"]):
            text = re.sub(r"\s+", " ", element.get_text(" ", strip=True))
            if element.name == "h2":
                match = _HEADING_YEAR.match(text)
                year = int(match.group(1)) if match else None
                if year:
                    years.add(year)
            elif element.name == "h4":
                match = _BLOCK.search(text) if year else None
                if match:
                    month = _MONTHS[match.group(1).lower()[:3]]
                    blocks.append((year, month, []))
                else:
                    blocks.append(None)
            elif (
                blocks
                and blocks[-1]
                and element.get("href", "").lower().endswith(".pdf")
            ):
                blocks[-1][2].append((text, urljoin(url, element["href"])))
        return years, [b for b in blocks if b]

    def _meetings(self, page_url: str, blocks: list[tuple], wanted: set[int]):
        meetings: dict[tuple, dict] = {}
        for year, month, links in blocks:
            # The same file listed twice under different labels is one
            # meeting: April 2020's "Special Meeting" and ordinary minutes
            # both link 10-29th-April-2020.pdf, the ordinary meeting.
            labels: dict[str, list[str]] = {}
            for text, href in links:
                labels.setdefault(href, []).append(text)

            dated, undated = [], []
            for href, texts in labels.items():
                text = (
                    texts[0]
                    if len(texts) == 1
                    else "Minutes "
                    + " ".join(t for t in texts if not _SPECIAL.search(t))
                )
                if _MINUTES.search(text):
                    kind = "minutes"
                elif _AGENDA.search(text):
                    kind = "agenda"
                else:
                    continue
                meeting = self._meeting_type(text + " " + href.rsplit("/", 1)[-1])
                date = _file_day(href, year, month)
                (dated if date else undated).append((kind, meeting, date, href))

            # Agendas first, so that where agenda and minutes disagree on
            # the day the agenda, written for the meeting, decides it.
            dated.sort(key=lambda p: p[0] != "agenda")
            block_meetings: dict[tuple, dict] = {}
            for kind, meeting, date, href in dated:
                same = next(
                    (
                        k
                        for k in block_meetings
                        if k[1] == meeting
                        and kind not in block_meetings[k]
                        and abs((k[0] - date).days) <= 1
                    ),
                    (date, meeting),
                )
                block_meetings.setdefault(same, {}).setdefault(kind, href)
            # An undated paper goes to the block's one dated meeting of its
            # type ("LHRASC_Minutes_of_Meeting_-_May_2026.pdf" to the 20 May
            # agenda's meeting). With none or several, it cannot be placed
            # without inventing a day, and is left out.
            for kind, meeting, _, href in undated:
                candidates = [k for k in block_meetings if k[1] == meeting]
                if len(candidates) == 1 and kind not in block_meetings[candidates[0]]:
                    block_meetings[candidates[0]][kind] = href
                else:
                    self.logger.info(
                        f"{self.council_name}: no day for {href} ({meeting}, "
                        f"{year}-{month:02d}); left out"
                    )

            for (date, meeting), slots in block_meetings.items():
                if date.year in wanted:
                    meetings[(date, meeting)] = (page_url, slots)
        return meetings

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        years, blocks = self._blocks(_CURRENT_URL)
        if not years:
            # The page always heads its year "<year> Meetings", so no
            # heading means the markup changed, whatever the date.
            raise RuntimeError(
                f"{self.council_name}: no '<year> Meetings' heading on {_CURRENT_URL}"
            )
        meetings = self._meetings(_CURRENT_URL, blocks, wanted)
        # The archive holds every year the current page does not. A
        # production run for the current year needs only the current page.
        if any(y not in years and y <= clock.current_year() for y in wanted):
            _, blocks = self._blocks(_ARCHIVE_URL)
            for key, value in self._meetings(_ARCHIVE_URL, blocks, wanted).items():
                meetings.setdefault(key, value)

        results = []
        for (date, meeting), (page_url, slots) in sorted(meetings.items()):
            agenda_url, minutes_url = slots.get("agenda"), slots.get("minutes")
            results.append(
                ScraperReturn(
                    name=meeting,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=page_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results and any(_owed_papers(y) for y in wanted):
            raise RuntimeError(
                f"{self.council_name}: no dated agendas or minutes for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
