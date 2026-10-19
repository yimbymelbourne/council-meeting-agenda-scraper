import calendar
import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://quilpie.qld.gov.au"
_LISTING_URL = f"{_BASE_URL}/council-meetings/"

# Every paper since 2011 is linked from this one WordPress page, filed in
# nested accordions: a year ("Meeting Agendas and Minutes 2025") holding a
# month ("Febuary 2025"), holding one link per document. The current year
# is a different accordion widget (div.cm-item) from the older years
# (details/summary), so the month is read from whichever encloses a link.
#
# The link text is the only place the meeting is described ("Agenda –
# Special Meeting of Council – 1 April 2025"). Upload folders do not match
# the meeting (2026's papers sit in /2026/02/), and the text sometimes drops
# the year ("Late Agenda – ... – Wednesday 12 February") or the day
# ("Agenda – February 2020"); the month accordion supplies what is missing.

# Papers that belong to a meeting but are not its agenda or minutes.
_NOT_PAPERS = re.compile(
    r"\blate\b|additional|supplementary|status\s+report|attachment|notice" r"|calendar",
    re.IGNORECASE,
)
_MINUTES = re.compile(r"\bmin(?:utes?|uted|tues)\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)
_POST_ELECTION = re.compile(r"post\s+election", re.IGNORECASE)
# Large agendas are split ("Pt.1", "_Part2"); part 1 carries the order of
# business and is the one kept.
_PART = re.compile(r"(?:\bpt\.?|part)\s*(\d)", re.IGNORECASE)

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTH_WORD = r"(jan|feb|febuary|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
_TEXT_DATE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH_WORD}\.?(?:,?\s+(20\d\d))?",
    re.IGNORECASE,
)
_HEADING = re.compile(rf"^{_MONTH_WORD}\s+(20\d\d)$", re.IGNORECASE)
_FILE_DATE = re.compile(
    rf"(?<!\d)(\d{{1,2}})-{_MONTH_WORD}-(20\d\d)(?!\d)|(?<!\d)(20\d\d)(\d\d)(\d\d)(?!\d)",
    re.IGNORECASE,
)

# A link whose file is dated more than this far from the date in its text is
# another meeting's file: "Agenda – Special Meeting of Council – 05 December
# 2024" links the 17 December ordinary agenda. A day or two either way is a
# typo in one of them ("...-Wednesday-4-July-2022.pdf" for the 6 July
# special meeting), and the text is kept.
_FILE_DATE_TOLERANCE_DAYS = 3


def _month(word: str) -> int:
    word = word.lower()
    return 2 if word.startswith("feb") else _MONTHS[word[:3]]


def _enclosing_month(link) -> tuple[Optional[int], Optional[int]]:
    """(year, month) from the accordion a link sits in."""
    for parent in link.parents:
        if parent.name == "details":
            heading = parent.find("summary")
        elif "cm-item" in (parent.get("class") or []):
            heading = parent.find("div", class_="cm-heading")
        else:
            continue
        match = _HEADING.match(heading.get_text(" ", strip=True)) if heading else None
        if match:
            return int(match.group(2)), _month(match.group(1))
    return None, None


def _file_date(url: str) -> Optional[datetime.date]:
    match = _FILE_DATE.search(url.rsplit("/", 1)[-1])
    if not match:
        return None
    try:
        if match.group(1):
            return datetime.date(
                int(match.group(3)), _month(match.group(2)), int(match.group(1))
            )
        return datetime.date(*(int(g) for g in match.group(4, 5, 6)))
    except ValueError:
        return None


# A new year's first papers go up in late January (29 January in 2026,
# 30 January in 2025), so for its first weeks the current year is empty. An empty year is an error only once this much of it has passed,
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
class QuilpieScraper(BaseScraper):
    def __init__(self):
        super().__init__("quilpie", "QLD", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _paper(self, link):
        """(kind, meeting type, year, month, day or None, rank, url)."""
        text = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
        url = urljoin(_LISTING_URL, link["href"])
        if not text or not url.lower().endswith(".pdf") or _NOT_PAPERS.search(text):
            return None
        if _MINUTES.search(text):
            kind = "minutes"
        elif _AGENDA.search(text):
            kind = "agenda"
        else:
            return None

        if _POST_ELECTION.search(text):
            meeting = "Post Election Meeting of Council"
        elif _SPECIAL.search(text):
            meeting = "Special Meeting of Council"
        else:
            meeting = "Ordinary Meeting of Council"

        year, month = _enclosing_month(link)
        day = None
        stated = _TEXT_DATE.search(text)
        if stated:
            day = int(stated.group(1))
            month = _month(stated.group(2))
            year = int(stated.group(3)) if stated.group(3) else year
        if year is None or month is None:
            return None

        if day:
            try:
                date = datetime.date(year, month, day)
            except ValueError:
                return None
            on_file = _file_date(url)
            if on_file and abs((on_file - date).days) > _FILE_DATE_TOLERANCE_DAYS:
                self.logger.info(
                    f"{self.council_name}: {text!r} links {url}, dated {on_file}; "
                    "left out"
                )
                return None

        part = _PART.search(text)
        rank = int(part.group(1)) if part else 0
        return kind, meeting, year, month, day, rank, url

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser"
        )

        # (date, meeting type) -> kind -> (rank, url)
        meetings: dict[tuple, dict] = {}
        undated = []
        seen = set()
        for link in soup.find_all("a", href=True):
            paper = self._paper(link)
            if not paper or paper[-1] in seen:
                continue
            seen.add(paper[-1])
            kind, meeting, year, month, day, rank, url = paper
            if year not in wanted:
                continue
            if day is None:
                undated.append(paper)
                continue
            slots = meetings.setdefault((datetime.date(year, month, day), meeting), {})
            if kind not in slots or rank < slots[kind][0]:
                slots[kind] = (rank, url)

        # A paper labelled only by month ("Agenda – February 2020",
        # "Confirmed Minutes – Ordinary Meeting of Council Feb 2021") goes to
        # the one meeting of its type that month, if there is exactly one.
        # Otherwise it cannot be placed without guessing a day, and is left
        # out.
        for kind, meeting, year, month, _, rank, url in undated:
            candidates = [
                key
                for key in meetings
                if key[1] == meeting and (key[0].year, key[0].month) == (year, month)
            ]
            if len(candidates) == 1 and kind not in meetings[candidates[0]]:
                meetings[candidates[0]][kind] = (rank, url)
            else:
                self.logger.info(
                    f"{self.council_name}: no single {meeting} in {year}-{month:02d} "
                    f"for {url}; left out"
                )

        results = []
        for (date, meeting), slots in sorted(meetings.items()):
            agenda_url = slots.get("agenda", (None, None))[1]
            minutes_url = slots.get("minutes", (None, None))[1]
            results.append(
                ScraperReturn(
                    name=meeting,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        # The page carries every year, so a page with no papers on it at
        # all has changed shape, whatever the date.
        if not seen:
            raise RuntimeError(
                f"{self.council_name}: no agendas or minutes on {_LISTING_URL}"
            )
        # Nothing for a requested year that is past its first weeks means
        # the year's markup changed, not a quiet year.
        if not results and any(_owed_papers(y) for y in wanted):
            raise RuntimeError(
                f"{self.council_name}: no agendas or minutes on {_LISTING_URL} for "
                f"{sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
