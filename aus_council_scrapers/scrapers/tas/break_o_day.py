import datetime
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup, Tag

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.bodc.tas.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/agendas-minutes/"
_SCHEDULE_URL = f"{_BASE_URL}/council/council-meetings/"

# Everything is on one WordPress page, a tab per year, each a run of
# paragraphs linking agendas and minutes and, from 2023, the meeting's audio
# recording. The difficulty is the date. Since 2022 most labels and file
# names give only the month ("Council Meeting Agenda – October 2026",
# October-2026-Council-Meeting-Agenda-PUBLIC.pdf), so the day comes from, in
# order of trust:
#
# 1. a full date on any paper of that meeting (2019–2021 file names carry it:
#    Council-Minutes_15-November-2021-PUBLIC.pdf);
# 2. the audio recording of that meeting, whose file is named for the moment
#    the recorder started (BODC_RECORD_21092026093344.mp3 is 21 September
#    2026), under a caption saying which meeting it is;
# 3. the council's published schedule for the current year ("Scheduled Council
#    Meetings for 2026 ... Monday 19 January"), for ordinary meetings only;
# 4. for past papers none of these reaches, the date printed on the paper's
#    own first page, read by hand and listed in _DATED_BY_FIRST_PAGE.
#
# A meeting none of these dates is left out with a warning rather than given
# an invented day.
_MONTH_NAMES = [
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
]
_MONTH = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_FULL_DATE = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s_\-–]+"
    + _MONTH
    + r"(?![a-z])[\s_\-–,]+(\d{4})",
    re.IGNORECASE,
)
_DOTTED_DATE = re.compile(r"(?<!\d)(\d{2})\.(\d{2})\.(\d{4})(?!\d)")
_RECORDER_DATE = re.compile(r"BODC_RECORD_(\d{2})(\d{2})(\d{4})", re.IGNORECASE)
_MONTH_YEAR = re.compile(
    r"(?<![a-z])" + _MONTH + r"(?![a-z])(?:[\s_\-–,]*(\d{4}))?", re.IGNORECASE
)
_AGM = re.compile(r"\bAGM\b|annual general", re.IGNORECASE)
_SPECIAL = re.compile(r"special|\bSCM\b", re.IGNORECASE)
_SCHEDULE_HEADING = re.compile(r"scheduled council meetings for (\d{4})", re.IGNORECASE)
_SCHEDULE_DAY = re.compile(
    r"^(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(\d{1,2})\s+"
    + _MONTH
    + r"$",
    re.IGNORECASE,
)

# Papers whose label and file name give only the month and that no
# recording or schedule dates: every 2022 ordinary meeting (no recordings were
# posted that year), May and September 2025 (their recordings are named
# Audio-Recording-May-2025 and Recording-1), and the 2023 and 2024 AGMs. Each
# date is the one on page 1 of the PDF, read on 20 Oct 2026; agenda and
# minutes agreed every time. Keyed by file name, so a re-uploaded paper falls
# back to the warning rather than taking a stale date. Reading page 1 at run
# time would cost a PDF download per paper and bloat the fixture, and these
# are closed years whose papers will not change.
_DATED_BY_FIRST_PAGE = {
    name: datetime.date(*ymd)
    for ymd, names in {
        (2022, 1, 17): (
            "Council-Agenda_January-2022-PUBLIC.pdf",
            "Council-Minutes_January-2022-PUBLIC.pdf",
        ),
        (2022, 2, 21): (
            "Council-Agenda_February-2022-PUBLIC-REDUCED.pdf",
            "Council-Minutes_February-2022-PUBLIC.pdf",
        ),
        (2022, 3, 21): (
            "Council-Agenda_March-2022-PUBLIC-REDUCED-4.pdf",
            "Council-Minutes_March-2022-PUBLIC.pdf",
        ),
        # A Wednesday, after the Easter Monday.
        (2022, 4, 20): (
            "Council-Agenda_April-2022-PUBLIC-REDUCED.pdf",
            "Council-Minutes_April-2022-PUBLIC.pdf",
        ),
        (2022, 5, 16): (
            "Council-Agenda_May-2022-PUBLIC-REDUCED.pdf",
            "Council-Minutes_May-2022-PUBLIC.pdf",
        ),
        (2022, 6, 27): (
            "Council-Agenda_June-2022-PUBLIC.pdf",
            "Council-Minutes_June-2022-PUBLIC.pdf",
        ),
        (2022, 7, 18): (
            "Council-Agenda_July-2022-PUBLIC-REDUCED.pdf",
            "Council-Minutes_July-2022-PUBLIC.pdf",
        ),
        (2022, 8, 15): (
            "Council-Agenda_August-2022-PUBLIC.pdf",
            "Council-Minutes_August-2022-PUBLIC.pdf",
        ),
        (2022, 9, 19): (
            "Council-Agenda_September-2022-PUBLIC.pdf",
            "Council-Minutes_September-2022-PUBLIC.pdf",
        ),
        (2022, 10, 17): (
            "Council-Agenda_October-2022-PUBLIC.pdf",
            "Council-Minutes_October-2022-PUBLIC.pdf",
        ),
        (2022, 11, 21): (
            "Council-Agenda_November-2022-FINAL-PUBLIC.pdf",
            "Council-Minutes_November-2022-PUBLIC-1.pdf",
        ),
        (2022, 12, 19): (
            "Council-Agenda_December-2022-PUBLIC.pdf",
            "Council-Minutes_December-2022-PUBLIC.pdf",
        ),
        (2023, 12, 12): (
            "Council-AGM-Agenda-December-2023.pdf",
            "Council-AGM-Minutes-December-2023.pdf",
        ),
        (2024, 12, 10): (
            "Council-AGM-Agenda-December-2024.pdf",
            "Council-AGM-Minutes-December-2024.pdf",
        ),
        (2025, 5, 19): (
            "May-2025-Council-Meeting-Agenda-PUBLIC.pdf",
            "Council-Meeting-Minutes-May-2025.pdf",
        ),
        (2025, 9, 15): (
            "September-2025-Meeting-Agenda-PUBLIC-LOW-RES.pdf",
            "September-2025-Meeting-Minutes-PUBLIC.pdf",
        ),
    }.items()
    for name in names
}

_NAMES = {
    "ordinary": "Ordinary Council Meeting",
    "special": "Special Council Meeting",
    "agm": "Annual General Meeting",
}


def _month_number(name: str) -> int:
    return next(
        i + 1 for i, m in enumerate(_MONTH_NAMES) if m.startswith(name[:3].lower())
    )


def _full_date(text: str) -> Optional[datetime.date]:
    for pattern in (_FULL_DATE, _DOTTED_DATE, _RECORDER_DATE):
        for match in pattern.finditer(text):
            day, month, year = match.groups()
            try:
                month_number = int(month) if month.isdigit() else _month_number(month)
                return datetime.date(int(year), month_number, int(day))
            except ValueError:
                continue
    return None


def _month(text: str, tab_year: int) -> Optional[tuple[int, int]]:
    match = _MONTH_YEAR.search(text)
    if not match:
        return None
    return int(match.group(2) or tab_year), _month_number(match.group(1))


def _kind_of_meeting(text: str) -> str:
    if _AGM.search(text):
        return "agm"
    if _SPECIAL.search(text):
        return "special"
    return "ordinary"


@dataclass
class _Paper:
    kind: str  # "agenda" or "minutes"
    meeting: str  # "ordinary", "special" or "agm"
    url: str
    label: str
    tab_year: int
    date: Optional[datetime.date]
    month: Optional[tuple[int, int]]


@register_scraper
class BreakODayScraper(BaseScraper):
    def __init__(self):
        super().__init__("break_o_day", "TAS", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _tabs(soup: BeautifulSoup) -> list[tuple[int, Tag]]:
        tabs = []
        for anchor in soup.select("#responsiveTabs ul.tabs-title a[href^='#tab-']"):
            year = anchor.get_text(strip=True)
            panel = soup.find(id=anchor["href"][1:])
            if panel and re.fullmatch(r"\d{4}", year):
                tabs.append((int(year), panel))
        return tabs

    @staticmethod
    def _papers(panel: Tag, tab_year: int) -> list[_Paper]:
        # One label is often split over two anchors to the same file
        # ("Council Meeting Minutes –" + "September 2026"), so consecutive
        # anchors sharing an href are joined.
        links: list[tuple[str, str]] = []
        for anchor in panel.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href.lower().endswith(".pdf"):
                continue
            text = anchor.get_text(" ", strip=True)
            if links and links[-1][0] == href:
                links[-1] = (href, f"{links[-1][1]} {text}".strip())
            else:
                links.append((href, text))

        papers = []
        for href, label in links:
            url = urljoin(_LISTING_URL, href)
            filename = unquote(url.rsplit("/", 1)[-1])
            text = f"{label} {filename}"
            if re.search(r"minute", text, re.IGNORECASE):
                kind = "minutes"
            elif re.search(r"agenda", text, re.IGNORECASE):
                kind = "agenda"
            else:
                # Attachments, the planning scheme codes listed in 2020.
                continue
            label_month = _month(label, tab_year)
            date = _full_date(label)
            if date is None:
                date = _full_date(filename)
                # A file name dated to another month is a stale upload name,
                # not this paper's date.
                if date and label_month and (date.year, date.month) != label_month:
                    date = None
            papers.append(
                _Paper(
                    kind=kind,
                    # The label says which meeting; a file name can carry
                    # noise ("Council-meeting-amended-minutes-April-AGM-
                    # Approved" is April's ordinary minutes).
                    meeting=_kind_of_meeting(label or filename),
                    url=url,
                    label=label,
                    tab_year=tab_year,
                    date=date,
                    month=label_month or _month(filename, tab_year),
                )
            )
        return papers

    @staticmethod
    def _recordings(panel: Tag) -> list[tuple[str, datetime.date]]:
        """(meeting kind, date) for each audio recording in a year tab.

        A recording's caption ("Audio Recording – October 2025 Special
        Council Meeting – click below") says which meeting it is, and the
        file name when it was recorded. A file filed under a caption for
        another month (the March 2026 file repeated under January's) is
        ignored.
        """
        recordings = []
        caption = ""
        for element in panel.find_all(["p", "source"]):
            if element.name == "p":
                text = element.get_text(" ", strip=True)
                if re.search(r"audio recording", text, re.IGNORECASE):
                    caption = text
                continue
            filename = unquote(element.get("src", "").split("?")[0].rsplit("/", 1)[-1])
            date = _full_date(filename)
            if not date or not caption:
                continue
            caption_month = _month(caption, date.year)
            if caption_month and caption_month[1] != date.month:
                continue
            recordings.append((_kind_of_meeting(caption), date))
        return recordings

    def _schedule(self) -> dict[tuple[int, int], datetime.date]:
        """The current year's ordinary meetings, keyed by (year, month)."""
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_SCHEDULE_URL), "html.parser"
        )
        lines = [
            line.strip() for line in soup.get_text("\n").splitlines() if line.strip()
        ]
        schedule = {}
        year = None
        for line in lines:
            heading = _SCHEDULE_HEADING.search(line)
            if heading:
                year = int(heading.group(1))
                continue
            match = _SCHEDULE_DAY.match(line)
            if year and match:
                try:
                    date = datetime.date(
                        year, _month_number(match.group(2)), int(match.group(1))
                    )
                except ValueError:
                    continue
                schedule[(date.year, date.month)] = date
            elif year and schedule:
                break
        if not schedule:
            self.logger.warning(
                f"{self.council_name}: no meeting schedule found on {_SCHEDULE_URL}"
            )
        return schedule

    @staticmethod
    def _date_by_position(papers: list[_Paper]) -> None:
        """Month an undated paper from the paper listed straight after it.

        "Council Meeting Minutes – PUBLIC" (Council-Meeting-Minutes-PUBLIC.pdf)
        sits in the 2026 tab between May's papers and April's agenda, and is
        the 20 April 2026 minutes. The page lists each month as minutes then
        agenda, so an undated paper takes the month of the next paper when
        that is the other kind, for the same type of meeting, and its own
        kind has no paper for that month yet.
        """
        for i, paper in enumerate(papers):
            if paper.date or paper.month or i + 1 >= len(papers):
                continue
            following = papers[i + 1]
            month = (
                (following.date.year, following.date.month)
                if following.date
                else following.month
            )
            if (
                following.kind == paper.kind
                or following.meeting != paper.meeting
                or following.tab_year != paper.tab_year
                or not month
            ):
                continue
            taken = any(
                other.kind == paper.kind
                and other.meeting == paper.meeting
                and ((other.date.year, other.date.month) if other.date else other.month)
                == month
                for other in papers
                if other is not paper
            )
            if not taken:
                paper.month = month

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Left to raise: this page is the only source of papers, and an empty
        # list would report a broken site as a council with no meetings.
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser"
        )
        tabs = self._tabs(soup)
        if not tabs:
            raise ValueError(f"{self.council_name}: no year tabs on {_LISTING_URL}")

        papers: list[_Paper] = []
        recordings: list[tuple[str, datetime.date]] = []
        for tab_year, panel in tabs:
            papers.extend(self._papers(panel, tab_year))
            recordings.extend(self._recordings(panel))
        self._date_by_position(papers)

        # The schedule only dates this year's papers that neither a full-date
        # paper nor a recording does, which in practice is the upcoming
        # meeting. Losing it costs that one meeting, not the year, so a
        # failure is reported and the rest still returned.
        schedule = {}
        if clock.current_year() in wanted:
            try:
                schedule = self._schedule()
            except Exception as error:
                self.logger.warning(
                    f"{self.council_name}: could not read {_SCHEDULE_URL}: {error}"
                )

        # Resolve each month-only paper to a day.
        for paper in papers:
            if paper.date or not paper.month:
                continue
            if paper.month[0] not in wanted:
                continue
            same_month = {
                other.date
                for other in papers
                if other.date
                and other.meeting == paper.meeting
                and (other.date.year, other.date.month) == paper.month
            }
            recorded = {
                date
                for kind, date in recordings
                if kind == paper.meeting and (date.year, date.month) == paper.month
            }
            for candidates in (same_month, recorded):
                if len(candidates) == 1:
                    paper.date = next(iter(candidates))
                    break
            if paper.date is None and paper.meeting == "ordinary":
                paper.date = schedule.get(paper.month)
            if paper.date is None:
                read = _DATED_BY_FIRST_PAGE.get(unquote(paper.url.rsplit("/", 1)[-1]))
                # Only when the label's month agrees, so a file re-used
                # under another month's label is not given the old date.
                if read and (read.year, read.month) == paper.month:
                    paper.date = read

        meetings: dict[tuple[datetime.date, str], dict[str, str]] = {}
        undated = set()
        for paper in papers:
            year = (
                paper.date.year if paper.date else (paper.month or (paper.tab_year,))[0]
            )
            if year not in wanted:
                continue
            if paper.date is None:
                undated.add(f"{paper.label or paper.url} ({paper.url})")
                continue
            # First link wins: an amended paper is listed above the original.
            meetings.setdefault((paper.date, paper.meeting), {}).setdefault(
                paper.kind, paper.url
            )

        if undated:
            self.logger.warning(
                f"{self.council_name}: no day for {len(undated)} paper(s), skipped: "
                + "; ".join(sorted(undated))
            )

        results = []
        for (date, meeting), found in sorted(meetings.items()):
            agenda_url = found.get("agenda")
            minutes_url = found.get("minutes")
            results.append(
                ScraperReturn(
                    name=_NAMES[meeting],
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
