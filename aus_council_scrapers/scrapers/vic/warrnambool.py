import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.alyka import filename_of, find_date
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.warrnambool.vic.gov.au"

# Two Drupal 10 views of the same meeting content type, each one table with
# no pager. /past-council-meetings holds every meeting since 2017 and gains a
# row as soon as a meeting has happened; /council-meetings holds the
# scheduled ones, which is where an agenda sits for the week before its
# meeting. Two requests cover any range, so years_filter only filters.
#
# robots.txt is Drupal's stock file and disallows neither path. The site is
# behind Cloudflare; the identifying client passed every request when this
# was written.
_LISTINGS = (
    f"{_BASE_URL}/council-meetings",
    f"{_BASE_URL}/past-council-meetings",
)

# Each row: a <time> with the meeting's local date and time as text
# ("Monday, October 5,  2026 - 4:00 pm"), the type ("Scheduled",
# "Additional", "Special", and before 2021 "Ordinary"), a link to the
# meeting's summary page, and the agenda and minutes cells. The <time>'s
# datetime attribute is that same local time labelled "Z", so the text is
# read rather than the attribute, which would be ten or eleven hours out if
# taken at its word.
#
# A meeting with two values in a multi-value field comes back as two rows:
# 4 May 2026 is listed twice, once with its minutes and once with the
# minutes of the hearings held that evening. Rows are grouped by summary
# page, and the hearings minutes lose to the meeting's own.
_HEARINGS = re.compile(r"hearing", re.IGNORECASE)

# Rows entered in 2020 carry the time the record was created ("11:43 am",
# "2:35 pm", "2:30 pm") rather than the meeting's, and older rows say 12:00
# am or pm for "unknown". From 2021 the field holds the meeting's start
# (5:45 pm, then 4:00 pm from 2026), bar one 1:20 pm stamp in August 2021,
# so a time is kept only from 2021 and only on the quarter hour.
_TIMES_FROM = 2021
_REAL_TIME = re.compile(
    r"^(?!12:00\s*[ap]m)\d{1,2}:(?:00|15|30|45)\s*[ap]m$", re.IGNORECASE
)

# The type column is not always what the papers say: 5 October 2020 is
# "Scheduled" but its agenda is "AGENDA Additional Council Meeting
# 5Oct2020", and 16 March 2020 is "Ordinary" with a Special agenda. The
# annual (statutory) meetings are typed Scheduled, Special or Additional in
# different years. So the papers' own filenames and the summary page's slug
# get a say in the name.
_ANNUAL = re.compile(r"annual|statutory", re.IGNORECASE)
_SPECIAL = re.compile(r"special", re.IGNORECASE)
_ADDITIONAL = re.compile(r"additional|additonal", re.IGNORECASE)
_TYPE_NAMES = {
    "scheduled": "Scheduled Council Meeting",
    "additional": "Additional Council Meeting",
    "special": "Special Council Meeting",
    "ordinary": "Ordinary Council Meeting",
}


@register_scraper
class WarrnamboolScraper(BaseScraper):
    def __init__(self):
        super().__init__("warrnambool", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _text(element) -> str:
        return re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()

    @staticmethod
    def _pdfs(row, field: str) -> list[str]:
        """The PDF links in one of a row's document cells.

        Two 2025 minutes are Word documents (1 September and 7 July);
        agenda_url and minutes_url are for PDFs, so those meetings keep only
        their agenda.
        """
        cell = row.select_one(f"td.views-field-field-{field}")
        if cell is None:
            return []
        return [
            urljoin(_BASE_URL, a["href"])
            for a in cell.find_all("a", href=True)
            if unquote(a["href"]).lower().split("?")[0].endswith(".pdf")
        ]

    @staticmethod
    def _filename_date(url: str) -> Optional[datetime.date]:
        name = filename_of(url)
        iso = re.search(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)", name)
        if iso:
            try:
                return datetime.date(
                    int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
                )
            except ValueError:
                return None
        found = find_date(name.replace("_", " ").replace("-", " "))
        return found[0] if found else None

    def _for_this_meeting(self, urls: list[str], date: datetime.date) -> list[str]:
        """Drop documents that name some other meeting's day.

        6 April 2021's minutes link is "5.6.1 Minutes WARG 15 March 2021.pdf",
        an advisory group's minutes. Only day and month are compared, since
        the year in these filenames is sometimes mistyped (4 April 2022's
        agenda is "2002-04-04 AGENDA ..."). A filename naming no date is kept.
        """
        kept = []
        for url in urls:
            named = self._filename_date(url)
            if named and (named.month, named.day) != (date.month, date.day):
                continue
            kept.append(url)
        return kept

    def _meeting_name(self, kind: str, context: str) -> str:
        if _ANNUAL.search(context):
            return "Annual Council Meeting"
        if _SPECIAL.search(context):
            return "Special Council Meeting"
        if _ADDITIONAL.search(context):
            return "Additional Council Meeting"
        return _TYPE_NAMES.get(kind.lower(), "Council Meeting")

    def _rows(self, html: str, page_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        rows = []
        for row in soup.select("table tr"):
            when = row.find("time")
            if when is None:
                continue
            stamp = self._text(when)
            day_part, _, time_part = stamp.partition(" - ")
            try:
                date = parse_date(day_part).date()
            except (ValueError, OverflowError):
                self.logger.warning(
                    f"Warrnambool: unreadable date {stamp!r} on {page_url}"
                )
                continue
            kind_cell = row.select_one("td.views-field-field-special-regular")
            summary = row.select_one("td.views-field-view-node a[href]")
            rows.append(
                {
                    "date": date,
                    "time": time_part.strip(),
                    "kind": self._text(kind_cell) if kind_cell else "",
                    "summary": (
                        urljoin(_BASE_URL, summary["href"]) if summary else page_url
                    ),
                    "agendas": self._pdfs(row, "agenda"),
                    "minutes": self._pdfs(row, "minutes"),
                }
            )
        return rows

    def _slug_date(self, summary_url: str) -> Optional[datetime.date]:
        slug = summary_url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
        found = find_date(slug)
        if found:
            return found[0]
        # "april-8-2020", "monday-july-24-2023"
        match = re.search(r"([a-z]+) (\d{1,2})(?:st|nd|rd|th)? (20\d{2})", slug)
        if match:
            try:
                return parse_date(" ".join(match.groups())).date()
            except (ValueError, OverflowError):
                return None
        return None

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Either listing failing raises: the upcoming page is the only place
        # a pre-meeting agenda appears, and the past page is everything else.
        rows = []
        for url in _LISTINGS:
            rows.extend(self._rows(self.fetcher.fetch_with_requests(url), url))

        meetings: dict[str, dict] = {}
        for row in rows:
            meeting = meetings.setdefault(
                row["summary"], {**row, "agendas": [], "minutes": []}
            )
            for field in ("agendas", "minutes"):
                for url in row[field]:
                    if url not in meeting[field]:
                        meeting[field].append(url)

        results = []
        for meeting in meetings.values():
            date = meeting["date"]
            # 8 April 2020 is filed under Monday 6 April, a data-entry date;
            # its summary page, agenda and minutes all say 8 April. Where the
            # slug names another day and a paper agrees with the slug, the
            # papers are right.
            slug_date = self._slug_date(meeting["summary"])
            if (
                slug_date
                and slug_date != date
                and any(
                    self._filename_date(u) == slug_date
                    for u in meeting["agendas"] + meeting["minutes"]
                )
            ):
                date = slug_date
            if date.year not in wanted:
                continue

            agendas = self._for_this_meeting(meeting["agendas"], date)
            minutes = self._for_this_meeting(meeting["minutes"], date)
            minutes.sort(key=lambda u: bool(_HEARINGS.search(filename_of(u))))
            agenda_url = agendas[0] if agendas else None
            minutes_url = minutes[0] if minutes else None
            if not agenda_url and not minutes_url:
                # Scheduled but not yet papered.
                continue

            context = " ".join(
                [meeting["summary"].rsplit("/", 1)[-1]]
                + [filename_of(u) for u in agendas[:1] + minutes[:1]]
            )
            results.append(
                ScraperReturn(
                    name=self._meeting_name(meeting["kind"], context),
                    date=date.isoformat(),
                    time=(
                        meeting["time"]
                        if date.year >= _TIMES_FROM
                        and _REAL_TIME.match(meeting["time"])
                        else None
                    ),
                    webpage_url=meeting["summary"],
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        results.sort(key=lambda m: m.date, reverse=True)
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
