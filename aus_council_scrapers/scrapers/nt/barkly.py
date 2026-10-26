import datetime
import json
import re
from typing import Optional
from urllib.parse import unquote

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.barkly.nt.gov.au"
_MEETINGS_URL = f"{_BASE_URL}/meetings"
# Barkly's site is built on Duda, and its meetings widget reads a Duda
# collection through the public runtime API: one JSON row per council
# meeting with its title, start time and links to the agenda and minutes
# PDFs on Duda's CDN. "003550a4" is the site's alias, the same id that
# appears in every file URL. The /meetings page carries the same papers in
# static lists too, up to May 2025. Council papers start in October 2022 on
# both, and the page says earlier minutes are available on request only.
# The static lists are not read, because they are hand-edited HTML with no
# reliable structure, but four of their links fix rows the collection gets
# wrong; those are in _FROM_STATIC_PAGE below.
#
# The collection "meetings-committee" holds the Finance, Audit and Risk,
# Animal Management and CEO Review committees; only council meetings are
# read. Local Authority papers exist only as static lists on the page.
_COLLECTION_URL = (
    f"{_BASE_URL}/rts/collections/public/003550a4/runtime/collection/meetings-council/data"
    "?pageSize=100&pageNumber={page}"
)
_SPECIAL = re.compile(r"special", re.IGNORECASE)
_CDN = "https://irp.cdn-website.com/003550a4/files/uploaded"
# Minutes links on the wrong row, found by reading each linked file's first
# page on 20 Oct 2026. Nothing in the file names gives these away (the files
# are called CONFIRMED.pdf and the like), so they are listed by row. Keyed by
# the row's date as well as the URL, so the file is still accepted if the
# council moves it to the row it belongs to.
_MISLINKED_MINUTES = {
    # The 19 December 2023 special meeting's minutes.
    (datetime.date(2024, 1, 29), f"{_CDN}/CONFIRMED.pdf"),
    # The 28 June 2024 ordinary meeting's minutes.
    (datetime.date(2024, 2, 6), f"{_CDN}/Confirmed-Minutes.pdf"),
    # The 6 March 2024 special meeting's minutes.
    (datetime.date(2024, 3, 27), f"{_CDN}/CONFIRMED-MINUTE-b7c4d625.pdf"),
}
# Papers the collection lacks and the /meetings page's static lists have,
# checked against page 1 of each file on 20 Oct 2026. Used only where the
# row's own link is missing or was dropped above, so a fix the council makes
# to the collection wins.
_FROM_STATIC_PAGE = {
    # The static page's "VIEW MINUTES" link for each of these rows; the
    # collection's link is another meeting's (see _MISLINKED_MINUTES).
    (
        datetime.date(2024, 1, 29),
        "minutes",
    ): f"{_CDN}/CONFIRMED-MINUTES_240306_103513.pdf",
    (datetime.date(2024, 2, 6), "minutes"): f"{_CDN}/SPECIAL-6224-UNCONFIRMED.pdf",
    (
        datetime.date(2024, 3, 27),
        "minutes",
    ): f"{_CDN}/Ordinary_Meeting_of_Council_-__0aAo8PbbB02aeS_nBBHRpw_v3272.pdf",
    # The collection's 29 May 2025 row links the 28 May 2026 agenda.
    (
        datetime.date(2025, 5, 29),
        "agenda",
    ): f"{_CDN}/Ordinary_Meeting_of_Council_-__zuFXB1ec706tT1nCnz2cYQ_REVIEWED_AGENDAV2PAST.pdf",
}
# A meeting with no row at all: the 19 December 2023 special meeting at
# 1:00 pm, whose minutes (CONFIRMED.pdf, page 1 "Tuesday 19 December 2023
# at 1:00 pm") are linked only under the 29 January 2024 meeting, in the
# collection and on the static page alike. No agenda for it is online.
_MISSING_ROWS = [
    (
        datetime.datetime(2023, 12, 19, 13, 0),
        "Tennant Creek - Special Meeting",
        None,
        f"{_CDN}/CONFIRMED.pdf",
    ),
]
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
# Dates written into the PDF file names, for spotting a link to another
# meeting's file: "OCM_Agenda_28May2026.pdf", "OC_24112022_AGN_859_AT.pdf",
# "Special_Meeting_of_Council_27+January+2026we.pdf".
_FILE_DATES = (
    (
        re.compile(
            r"(?<!\d)(\d{1,2})[\s+_\-]*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s+_\-]*(20\d\d)",
            re.IGNORECASE,
        ),
        "dMy",
    ),
    (re.compile(r"(?<!\d)(\d{2})(\d{2})(20\d\d)(?!\d)"), "dmy"),
    (re.compile(r"(?<!\d)(20\d\d)-(\d{2})-(\d{2})(?!\d)"), "ymd"),
)


def _file_date(url: str) -> Optional[datetime.date]:
    name = unquote(url.rsplit("/", 1)[-1])
    for pattern, order in _FILE_DATES:
        for match in pattern.finditer(name):
            a, b, c = match.groups()
            try:
                if order == "dMy":
                    return datetime.date(int(c), _MONTHS[b[:3].lower()], int(a))
                if order == "dmy":
                    return datetime.date(int(c), int(b), int(a))
                return datetime.date(int(a), int(b), int(c))
            except ValueError:
                continue
    return None


def _start(data: dict) -> Optional[datetime.datetime]:
    # Newer rows carry an ISO local time ("2026-07-30T09:00"), older ones a
    # text one ("May 29 2025 08:30").
    for key, fmt in (
        ("start_time", "%Y-%m-%dT%H:%M"),
        ("start_time_text", "%b %d %Y %H:%M"),
    ):
        value = (data.get(key) or "").strip()
        if not value:
            continue
        try:
            return datetime.datetime.strptime(
                value[:16] if key == "start_time" else value, fmt
            )
        except ValueError:
            continue
    return None


@register_scraper
class BarklyScraper(BaseScraper):
    def __init__(self):
        super().__init__("barkly", "NT", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _rows(self) -> list[dict]:
        rows = []
        page = 0
        while True:
            # Left to raise: the collection is the only source, and an
            # empty list would report a broken API as no meetings.
            body = json.loads(
                self.fetcher.fetch_with_requests(_COLLECTION_URL.format(page=page))
            )
            rows.extend(value.get("data") or {} for value in body.get("values") or [])
            total_pages = (body.get("page") or {}).get("totalPages") or 1
            page += 1
            if page >= total_pages:
                return rows

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        meetings = []
        for data in self._rows():
            start = _start(data)
            if start is None:
                if data:
                    self.logger.warning(
                        f"{self.council_name}: no start time on {data.get('title')!r}; skipped"
                    )
                continue
            title = re.sub(r"\s+", " ", data.get("title") or "").strip()
            agenda_url = (data.get("agenda") or "").strip() or None
            # Confirmed minutes are added beside the draft once adopted.
            minutes_url = (
                (data.get("minutes_confirmed") or "").strip()
                or (data.get("minutes") or "").strip()
                or None
            )
            if (start.date(), minutes_url) in _MISLINKED_MINUTES:
                minutes_url = None
            meetings.append([start, title, agenda_url, minutes_url])

        # The 29 May 2025 row's agenda is OCM_Agenda_28May2026.pdf, the
        # 28 May 2026 meeting's agenda, which that row also links. A file
        # dated for another listed meeting is that meeting's paper, not this
        # one's. A file date matching no meeting is left alone, since
        # upload names are often just wrong.
        dates = {m[0].date() for m in meetings}
        for meeting in meetings:
            for index in (2, 3):
                url = meeting[index]
                file_date = _file_date(url) if url else None
                if file_date and file_date != meeting[0].date() and file_date in dates:
                    self.logger.info(
                        f"{self.council_name}: {url} belongs to {file_date}, not {meeting[0].date()}"
                    )
                    meeting[index] = None

        for meeting in meetings:
            for index, kind in ((2, "agenda"), (3, "minutes")):
                if meeting[index] is None:
                    meeting[index] = _FROM_STATIC_PAGE.get((meeting[0].date(), kind))
        listed = {m[0].date() for m in meetings}
        meetings.extend(
            list(row) for row in _MISSING_ROWS if row[0].date() not in listed
        )

        results = []
        for start, title, agenda_url, minutes_url in sorted(
            meetings, key=lambda m: m[0]
        ):
            if start.year not in wanted or not (agenda_url or minutes_url):
                continue
            # Titles are "Tennant Creek - Ordinary Council Meeting", the town
            # first; some omit it.
            location = None
            if " - " in title:
                location, title = (part.strip() for part in title.split(" - ", 1))
            results.append(
                ScraperReturn(
                    name=(
                        "Special Council Meeting"
                        if _SPECIAL.search(title)
                        else "Ordinary Council Meeting"
                    ),
                    date=start.date().isoformat(),
                    time=start.strftime("%H:%M"),
                    webpage_url=_MEETINGS_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                    location=location,
                )
            )

        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
