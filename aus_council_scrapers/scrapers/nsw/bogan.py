import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://bogan.nsw.gov.au"
_LISTING_URL = f"{_BASE_URL}/your-council/council-meeting-minutes-business-papers"

# Bogan Shire Council's papers, 2020 on, are all on one server-rendered
# Kentico page: an accordion per year, each a table of Month | Date |
# Documents. (The per-year folders under the page are empty.) A month's row
# lists every paper for every meeting that month in one cell, so a row is
# not a meeting:
#
#   May | 15/22 | Business paper, Estimates Business Paper,
#                 Minutes Part 1, Minutes Part 2, Recording, Recording
#
# Each paper is assigned a meeting by what it says it is—an estimates
# (budget) meeting, an extraordinary meeting, or the ordinary meeting—and a
# day. The day is the one in its filename when the filename gives one
# ("Business_Paper_Budget_Estimates_Meeting_15_May_2025"), otherwise the
# row's day when only one of the row's days is left unclaimed by the other
# meetings that month. A paper that cannot be pinned to one day is left out
# rather than guessed: December 2021 lists two extraordinary meetings (1/24)
# and two of their papers name neither day.
#
# The table is kept by hand, so a paper is also checked against its row. A
# filename that names another month or year belongs to another meeting
# (March 2023's business paper is February's file; the "April" estimates
# paper of 2020 is dated 14 May). A link labelled Minutes whose file is a
# business paper (July 2021, November 2020), or the reverse, is left out.
#
# Attachments, late reports, "business not included" and recordings are not
# the agenda or minutes. A business paper in parts is represented by Part 1,
# which carries the order of business.
_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
# "26 february 2026", "18 december" (no year), "october 26 2023",
# "24 10 2024" and "21 05 026" (sic) once separators are spaces.
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}}) ({_MONTH})\b(?: (\d{{4}}))?")
_MONTH_DAY = re.compile(rf"\b({_MONTH}) (\d{{1,2}}) (\d{{4}})\b")
_NUMERIC = re.compile(r"(?<!\d)(\d{1,2}) (\d{1,2}) (\d{4}|0\d\d)(?!\d)")
_MONTH_ONLY = re.compile(rf"\b({_MONTH})\b(?: (\d{{4}}))?")

_ESTIMATES = re.compile(r"estimate", re.IGNORECASE)
_EXTRAORDINARY = re.compile(r"extra\s*-?\s*ordinary", re.IGNORECASE)
_MINUTES = re.compile(r"minutes", re.IGNORECASE)
_BUSINESS_PAPER = re.compile(r"bu[si]{2}ness\s*paper", re.IGNORECASE)
_NOT_A_PAPER = re.compile(
    r"late report|not included|attachment|recording", re.IGNORECASE
)
_PART = re.compile(r"\bpart\s*(\d+)", re.IGNORECASE)

# Date cells the council typed wrong, for months whose filenames give no day,
# so the row's day would stand. Keyed (year, month, the row's day), to the
# day the papers' covers give:
# - April 2021's row says 27; the business paper and minutes covers both read
#   "22 April 2021" (a Thursday).
# - March 2022's row says 28; the minutes read "Minutes of the Ordinary
#   Meeting of Bogan Shire Council 24 March 2022" (a Thursday).
_ROW_DAY_FIXES = {
    (2021, 4, 27): 22,
    (2022, 3, 28): 24,
}

# Ordinary meetings are on Thursdays (75 of the 84 meetings 2020 to 2026). An
# ordinary meeting dated only by its row on another weekday is logged, since
# that is how the two typos above were found.
_ORDINARY_WEEKDAY = 3

_NAMES = {
    "ordinary": "Ordinary Council Meeting",
    "extraordinary": "Extraordinary Council Meeting",
    "estimates": "Budget Estimates Meeting",
}


def _words(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _filename_words(url: str) -> str:
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    name = re.sub(r"\.pdf\.aspx$", "", name, flags=re.IGNORECASE)
    return _words(name)


class _Paper:
    def __init__(self, url: str, label: str, kind: str, meeting: str):
        self.url = url
        self.label = label
        self.kind = kind
        self.meeting = meeting
        self.day: Optional[int] = None


@register_scraper
class BoganScraper(BaseScraper):
    def __init__(self):
        super().__init__("bogan", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser")

        accordion = soup.select_one("div.accordion")
        cards = accordion.find_all("div", class_="card", recursive=False) if accordion else []
        if not cards:
            raise RuntimeError(f"{self.council_name}: no year sections at {_LISTING_URL}")

        results: list[ScraperReturn] = []
        for card in cards:
            heading = card.find(["h2", "h3", "h4", "button", "a"])
            year_match = re.search(r"\b(20\d\d)\b", heading.get_text(" ", strip=True) if heading else "")
            if not year_match:
                continue
            year = int(year_match[1])
            if year not in wanted:
                continue
            for row in card.select("tbody tr"):
                results.extend(self._row(row, year))

        if not results:
            self.logger.warning(
                f"{self.council_name}: no meetings with papers for {sorted(wanted)} "
                f"at {_LISTING_URL}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    def _label(self, link: Tag) -> str:
        # The link holds a "(PDF 23.8MB)" file-info span; the label is the
        # rest. Some links sit inside a file-info span themselves, so only
        # spans within the link count.
        def in_file_info(text) -> bool:
            for parent in text.parents:
                if parent is link:
                    return False
                if "file-info" in (parent.get("class") or []):
                    return True
            return False

        parts = [s for s in link.find_all(string=True) if not in_file_info(s)]
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    def _papers(self, cell: Tag, month: int, year: int) -> list[_Paper]:
        papers = []
        for link in cell.find_all("a", href=True):
            url = urljoin(_LISTING_URL, link["href"].strip())
            if ".pdf" not in urlparse(url).path.lower():
                continue
            label = self._label(link)
            filename = _filename_words(url)
            if _NOT_A_PAPER.search(label):
                continue
            label_minutes = bool(_MINUTES.search(label))
            label_paper = bool(_BUSINESS_PAPER.search(label))
            file_minutes = "minutes" in filename
            file_paper = "business paper" in filename
            if label_minutes:
                if file_paper and not file_minutes:
                    self.logger.warning(
                        f"{self.council_name}: link {label!r} for {month}/{year} is a "
                        f"business paper ({url}); left out"
                    )
                    continue
                kind = "minutes"
            elif label_paper or file_paper:
                if file_minutes and not file_paper:
                    continue
                kind = "agenda"
            else:
                # "Extraordinary Meeting" on its own says which meeting, not
                # which paper.
                continue
            part = _PART.search(label)
            if kind == "agenda" and part and part[1] != "1":
                continue

            both = f"{label} {filename}"
            if _ESTIMATES.search(both):
                meeting = "estimates"
            elif _EXTRAORDINARY.search(both):
                meeting = "extraordinary"
            else:
                meeting = "ordinary"
            paper = _Paper(url, label, kind, meeting)

            named = self._named_day(filename, month, year)
            if named is False:
                self.logger.warning(
                    f"{self.council_name}: {url} is listed under {month}/{year} but "
                    f"names another month; left out"
                )
                continue
            paper.day = named
            papers.append(paper)
        return papers

    @staticmethod
    def _named_day(words: str, month: int, year: int):
        """The day the filename gives for this row's month, None when it
        gives none, or False when it names a different month or year."""
        for pattern, order in ((_DAY_MONTH, "dmy"), (_MONTH_DAY, "mdy")):
            match = pattern.search(words)
            if not match:
                continue
            if order == "dmy":
                day, named_month, named_year = int(match[1]), _MONTHS[match[2]], match[3]
            else:
                named_month, day, named_year = _MONTHS[match[1]], int(match[2]), match[3]
            if named_month != month or (named_year and int(named_year) != year):
                return False
            return day
        numeric = _NUMERIC.search(words)
        if numeric:
            day, named_month, named_year = int(numeric[1]), int(numeric[2]), numeric[3]
            # "21-05-026" is how one 2026 paper is named.
            named_year = int(named_year) + (2000 if len(named_year) == 3 else 0)
            if named_month != month or named_year != year:
                return False
            return day
        month_only = _MONTH_ONLY.search(words)
        if month_only:
            if _MONTHS[month_only[1]] != month or (
                month_only[2] and int(month_only[2]) != year
            ):
                return False
        return None

    def _row(self, row: Tag, year: int) -> list[ScraperReturn]:
        cells = row.find_all("td")
        if len(cells) < 3:
            return []
        month_word = _words(cells[0].get_text(" ", strip=True))
        month = _MONTHS.get(month_word)
        if month is None:
            self.logger.warning(f"{self.council_name}: unreadable month {month_word!r}")
            return []
        days = [int(d) for d in re.findall(r"\d{1,2}", cells[1].get_text(" ", strip=True))]
        days = [_ROW_DAY_FIXES.get((year, month, d), d) for d in days]
        papers = self._papers(cells[2], month, year)
        if not papers:
            return []

        # The ordinary meeting is always in the Date cell, so an ordinary
        # paper naming some other day is naming the day it was issued
        # ("17_March_2021_Ordinary_Business_Paper" for the 25 March
        # meeting). An extraordinary or estimates meeting is not always
        # there: June 2021 lists 24 only, and the extraordinary minutes are
        # for 28 June.
        for paper in papers:
            if days and paper.day not in (None, *days) and paper.meeting == "ordinary":
                paper.day = None

        # Days a meeting's own filenames claim; a day claimed by another
        # meeting cannot be this one's.
        claimed: dict[str, set[int]] = {}
        for paper in papers:
            if paper.day is not None:
                claimed.setdefault(paper.meeting, set()).add(paper.day)
        for paper in papers:
            if paper.day is not None:
                continue
            others = set().union(*(d for m, d in claimed.items() if m != paper.meeting))
            if days:
                candidates = set(days) - others
            else:
                candidates = claimed.get(paper.meeting, set())
            if len(candidates) == 1:
                paper.day = candidates.pop()
                if (
                    days
                    and paper.meeting == "ordinary"
                    and paper.day not in claimed.get("ordinary", set())
                    and datetime.date(year, month, paper.day).weekday() != _ORDINARY_WEEKDAY
                ):
                    self.logger.warning(
                        f"{self.council_name}: ordinary meeting dated "
                        f"{paper.day}/{month}/{year} by the Date cell alone, not a "
                        f"Thursday; check the covers of {paper.url}"
                    )
            else:
                self.logger.warning(
                    f"{self.council_name}: cannot tell which {month}/{year} meeting "
                    f"{paper.label!r} ({paper.url}) is for; left out"
                )

        meetings: dict[tuple[int, str], dict[str, str]] = {}
        for paper in papers:
            if paper.day is None:
                continue
            found = meetings.setdefault((paper.day, paper.meeting), {})
            if paper.kind in found:
                continue
            if found.get("agenda" if paper.kind == "minutes" else "minutes") == paper.url:
                continue
            found[paper.kind] = paper.url

        results = []
        for (day, meeting), found in sorted(meetings.items()):
            try:
                meeting_date = datetime.date(year, month, day)
            except ValueError:
                self.logger.warning(
                    f"{self.council_name}: no such date {day}/{month}/{year}"
                )
                continue
            agenda_url = found.get("agenda")
            minutes_url = found.get("minutes")
            results.append(
                ScraperReturn(
                    name=_NAMES[meeting],
                    date=meeting_date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return results
