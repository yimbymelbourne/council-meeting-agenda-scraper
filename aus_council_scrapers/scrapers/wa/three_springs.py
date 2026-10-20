import calendar
import datetime
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.threesprings.wa.gov.au"
_YEAR_URL = (
    _BASE_URL
    + "/index.php/our-council/council-meetings/{year}-council-meeting-documents"
)

# A Joomla site with one hand-edited table per year (2020 onwards). The rows
# run in order: a month ("February 2025"), a meeting ("Ordinary Council
# Meeting", "Special Council Meeting 12 June 2025", "SCM - 5 February 2024"),
# then one row per paper ("Agenda", "Attachment Book", "Minutes", "Audio
# Recording"). /images/, where the PDFs are, is not in robots.txt.
#
# The table is typed by hand, and copy-and-paste shows. Most meeting rows
# carry no day, so the day comes from the file names (Agenda_-_OCM_26.02.25,
# Signed_Minutes_of_SCM_09.08.21), and some links belong to another meeting:
# the August 2021 special meeting's "Agenda" is the 25 August ordinary
# agenda, the 1 June 2023 special meeting's is the 28 June ordinary one, the
# cancelled April 2025 meeting lists May's agenda, March 2024's audit
# committee lists the ordinary minutes. So a meeting's day is taken only
# from its own row or from a file that names the right kind of meeting and
# falls in the right month, and a link dated more than a week from the
# meeting is dropped. A meeting whose day cannot be established that way
# (most of August to November 2020) is left out rather than given one.
# Development assessment panel meetings (state panels whose papers are on
# planning.wa.gov.au) and the community grants committee are not read.

_MONTH_NAMES = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTH_NAMES.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTH_NAMES["sept"] = 9
_MONTH = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|decmber)"

_MONTH_ROW = re.compile(rf"^{_MONTH}\s+(20\d\d)\b", re.IGNORECASE)
_DATE_ROW = re.compile(rf"^(\d{{1,2}})\s+{_MONTH}\s+(20\d\d)$", re.IGNORECASE)
_PAPER_ROW = re.compile(
    r"^(?:c\s*onfirmed\s+)?(agenda|minutes|attachments?|audio|regional)\b",
    re.IGNORECASE,
)

# Dates as the rows write them ("12 June 2025", "30/05/2023") and as the
# file names do ("26.02.25", "11.03.2026", "24_February_2021", "16_Dec_20",
# "1April_2020").
_TEXT_DATE = re.compile(rf"\b(\d{{1,2}})\s+{_MONTH}\s+(20\d\d)\b", re.IGNORECASE)
_SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b")
_DOTTED = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.((?:20)?\d\d)(?![\d])")
_WORDED = re.compile(
    rf"(?<![\d])(\d{{1,2}})[_ -]*{_MONTH}[_ -]+((?:20)?\d\d)(?![\d])", re.IGNORECASE
)

_TOLERANCE_DAYS = 7

# Meetings filed under the wrong kind. The 26 October 2022 meeting sits
# under a "Special Council Meeting" row, but its agenda's first page reads
# "An ordinary meeting of Council is called for Wednesday, 26 October 2022",
# and that month's "Ordinary Council Meeting" row links only November's
# minutes. Neither file name says which kind it was, so nothing in the
# table can catch it.
_REFILED = {
    (datetime.date(2022, 10, 26), "Special Council Meeting"): (
        "Ordinary Council Meeting"
    ),
}

# Each year's page is made during that year, so early January may have
# none, or an empty table. A year with no meetings is an error only once
# this much of it has passed, the rule CraftMeetingsModuleScraper uses.
_NEW_YEAR_GRACE_DAYS = 90


def _owed_papers(year: int) -> bool:
    """Whether a year has run long enough that it must have papers."""
    today = clock.today()
    return year < today.year or (
        year == today.year
        and (today - datetime.date(year, 1, 1)).days >= _NEW_YEAR_GRACE_DAYS
    )


def _year(text: str) -> int:
    year = int(text)
    return year + 2000 if year < 100 else year


def _month(text: str) -> int:
    text = text.lower()
    if text == "decmber":
        return 12
    return _MONTH_NAMES.get(text) or _MONTH_NAMES[text[:3]]


def _file_date(url: str) -> Optional[datetime.date]:
    name = url.rsplit("/", 1)[-1]
    for pattern, order in ((_DOTTED, "dmy"), (_WORDED, "dMy")):
        match = pattern.search(name)
        if not match:
            continue
        day, month, year = match.groups()
        try:
            month = int(month) if order == "dmy" else _month(month)
            return datetime.date(_year(year), month, int(day))
        except (ValueError, KeyError):
            continue
    return None


def _row_date(text: str) -> Optional[datetime.date]:
    match = _TEXT_DATE.search(text)
    try:
        if match:
            return datetime.date(
                int(match.group(3)), _month(match.group(2)), int(match.group(1))
            )
        match = _SLASH_DATE.search(text)
        if match:
            return datetime.date(
                int(match.group(3)), int(match.group(2)), int(match.group(1))
            )
    except ValueError:
        return None
    return None


def _kind_of_meeting(text: str) -> Optional[str]:
    if re.search(r"development assessment|\bDAP\b|community fund", text, re.I):
        return None
    if re.search(r"\baudit\b|\bARIC\b|risk", text, re.I):
        return "Audit and Risk Committee Meeting"
    if re.search(r"elector", text, re.I):
        return "Annual Electors Meeting"
    if re.search(r"\bspecial\b|\bSCM\b", text, re.I):
        return "Special Council Meeting"
    if re.search(r"\bordinary\b|\bOCM\b", text, re.I):
        return "Ordinary Council Meeting"
    return None


# File names that say which kind of meeting they are for. A file naming the
# wrong kind ("Agenda_25_August_2021_OCM.pdf" under a special meeting) is
# another meeting's paper.
_NAMES_KIND = {
    "Ordinary Council Meeting": re.compile(r"(?<![A-Z])OCM(?![A-Z])|ordinary", re.I),
    "Special Council Meeting": re.compile(r"(?<![A-Z])SCM(?![A-Z])|special", re.I),
    "Audit and Risk Committee Meeting": re.compile(
        r"audit|ARIC|(?<![A-Z])AR(?![A-Z])", re.I
    ),
    "Annual Electors Meeting": re.compile(r"elector", re.I),
}


def _names_other_kind(url: str, meeting: str) -> bool:
    name = url.rsplit("/", 1)[-1]
    if _NAMES_KIND[meeting].search(name):
        return False
    return any(p.search(name) for kind, p in _NAMES_KIND.items() if kind != meeting)


@dataclass
class _Block:
    meeting: str
    year: int
    month: int
    stated: Optional[datetime.date]
    moved: bool  # the month row says the meeting was moved
    papers: dict = field(default_factory=dict)  # kind -> url


@register_scraper
class ThreeSpringsScraper(BaseScraper):
    def __init__(self):
        super().__init__("three_springs", "WA", _BASE_URL)

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(years_filter)
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _blocks(self, html: str, url: str, page_year: int) -> list[_Block]:
        soup = BeautifulSoup(html, "html.parser")
        blocks: list[_Block] = []
        year, month, cancelled, moved = page_year, None, False, False
        current: Optional[_Block] = None
        for row in soup.select("table tr"):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            text = re.sub(r"\s+", " ", cells[0].get_text(" ", strip=True)).strip()
            if not text:
                continue
            month_row = _MONTH_ROW.match(text) or _DATE_ROW.match(text)
            if month_row:
                groups = month_row.groups()
                month, year = _month(groups[-2]), int(groups[-1])
                cancelled = bool(re.search(r"cancel", text, re.I))
                moved = bool(re.search(r"chang|moved|postpone", text, re.I))
                current = None
                continue
            paper = _PAPER_ROW.match(text)
            if paper:
                if current is None:
                    continue
                kind = paper.group(1).lower()
                if kind not in ("agenda", "minutes") and not text.lower().endswith(
                    "minutes"
                ):
                    continue
                kind = "minutes" if "minutes" in text.lower() else kind
                link = row.find("a", href=True)
                if link and kind not in current.papers:
                    href = urljoin(url, link["href"])
                    if href.lower().split("?")[0].endswith(".pdf") and not re.search(
                        r"attachment", href, re.I
                    ):
                        current.papers[kind] = href
                continue
            meeting = _kind_of_meeting(text)
            if meeting is None or month is None:
                # A notice, a DAP application, "No meeting": anything that
                # follows it until the next meeting row is not read.
                current = None
                continue
            current = _Block(meeting, year, month, _row_date(text), moved)
            if not cancelled:
                blocks.append(current)
        return blocks

    def _date(self, block: _Block) -> Optional[datetime.date]:
        if block.stated:
            return block.stated
        # File names are the only other witness, and both kinds get the day
        # wrong. Agendas are sometimes named for the day the notice went
        # out ("Agenda_OCM_13_March_2020" calls the meeting for Wednesday 18
        # March), minutes for some other day ("..._OCM_24_May_2021" for the
        # 26 May meeting, "..._OCM_23.03.23" for 22 March, "OCM_2.07.21" for
        # 28 July). Each was checked against the agenda's own first page. So:
        # agreement between the two settles it; otherwise an ordinary
        # meeting's day must be a Wednesday, the day the council sits (the
        # two that are not, 24 February 2026 and 23 October 2025, have
        # agenda and minutes agreeing); a special or committee meeting's
        # notice-dated agenda gives way to the later minutes.
        last = datetime.date(
            block.year, block.month, calendar.monthrange(block.year, block.month)[1]
        )
        named = {}
        for kind in ("agenda", "minutes"):
            url = block.papers.get(kind)
            if not url or _names_other_kind(url, block.meeting):
                continue
            date = _file_date(url)
            if not date or date.weekday() >= 5:
                continue
            if (date.year, date.month) == (block.year, block.month) or (
                # "September 2023 (OCM Changed to 4 October 23)"
                block.moved
                and 0 < (date - last).days <= 31
            ):
                named[kind] = date
        dates = set(named.values())
        if len(dates) == 1 and len(named) == 2:
            return dates.pop()
        if block.meeting == "Ordinary Council Meeting":
            wednesdays = {d for d in dates if d.weekday() == 2}
            return wednesdays.pop() if len(wednesdays) == 1 else None
        if dates:
            return max(dates)
        return None

    @staticmethod
    def _belongs(url: str, meeting: str, date: datetime.date) -> bool:
        stated = _file_date(url)
        if stated and abs((stated - date).days) <= 1:
            # Dated for this meeting, whatever kind it names: the 12 June
            # 2025 special meeting's minutes are "13._OCM_12.06.25_public".
            return True
        if _names_other_kind(url, meeting):
            return False
        if stated is None or abs((stated - date).days) <= _TOLERANCE_DAYS:
            return True
        # The wrong year on the right day: the 3 February 2025 electors'
        # papers are Agenda_03.02.24.pdf and ..._Meeting_03.02.24.pdf, and
        # the 13 December 2023 minutes are ..._OCM_13.12.24.pdf.
        return (stated.month, stated.day) == (date.month, date.day) and abs(
            stated.year - date.year
        ) == 1

    def _year_meetings(self, year: int) -> list[ScraperReturn]:
        url = _YEAR_URL.format(year=year)
        html = self.fetcher.fetch_with_requests(url)
        blocks = self._blocks(html, url, year)
        if not blocks:
            # Every year page lists its meetings a month at a time, ahead
            # of time (2026's has October to December rows already), so no
            # meeting rows at all means the table changed shape.
            raise RuntimeError(f"{self.council_name}: no meeting rows on {url}")
        records: dict[tuple, ScraperReturn] = {}
        for block in blocks:
            date = self._date(block)
            if date is None:
                if block.papers:
                    self.logger.info(
                        f"{self.council_name}: no day for {block.meeting} in "
                        f"{block.year}-{block.month:02d}; left out"
                    )
                continue
            papers = {
                kind: href
                for kind, href in block.papers.items()
                if self._belongs(href, block.meeting, date)
            }
            if not papers or date.year != year:
                continue
            name = _REFILED.get((date, block.meeting), block.meeting)
            key = (date, name)
            if key in records:
                # June 2026's special meeting is listed twice.
                continue
            records[key] = ScraperReturn(
                name=name,
                date=date.isoformat(),
                time=None,
                webpage_url=url,
                agenda_url=papers.get("agenda"),
                minutes_url=papers.get("minutes"),
                download_url=papers.get("agenda") or papers.get("minutes"),
            )
        return self._one_meeting_per_file(list(records.values()))

    @staticmethod
    def _one_meeting_per_file(records: list[ScraperReturn]) -> list[ScraperReturn]:
        """A file listed under two meetings goes to the one its name dates.

        The minutes of the special meeting called for 30 May 2023 and held
        on 1 June are listed under both rows.
        """
        owners: dict[str, list[ScraperReturn]] = {}
        for record in records:
            for url in (record.agenda_url, record.minutes_url):
                if url:
                    owners.setdefault(url, []).append(record)
        for url, holders in owners.items():
            if len(holders) < 2:
                continue
            stated = _file_date(url)
            keep = min(
                holders,
                key=lambda r: abs((stated - r.cleaned_date).days) if stated else 0,
            )
            for record in holders:
                if record is keep:
                    continue
                if record.agenda_url == url:
                    record.agenda_url = None
                if record.minutes_url == url:
                    record.minutes_url = None
                record.download_url = record.agenda_url or record.minutes_url
        return [r for r in records if r.agenda_url or r.minutes_url]

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        results, errors = [], []
        for year in self._wanted_years():
            if year > clock.current_year():
                # Each year's page is created during that year; a request
                # for a later year only finds the site's 404 page.
                continue
            try:
                results.extend(self._year_meetings(year))
            except Exception as e:
                self.logger.warning(f"{self.council_name}: could not read {year}: {e}")
                errors.append(e)
        if not results and any(_owed_papers(y) for y in self._wanted_years()):
            if errors:
                raise errors[-1]
            raise RuntimeError(
                f"{self.council_name}: no agendas or minutes for "
                f"{self._wanted_years()}"
            )
        results.sort(key=lambda r: (r.cleaned_date, r.name))
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
