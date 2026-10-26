"""Councils publishing through eScribe (`*.escribemeetings.com`).

eScribe's public portal is a calendar page whose script asks an ASP.NET page
method for the meetings in a date range:

    POST <portal>/MeetingsCalendarView.aspx/GetCalendarMeetings
    {"calendarStartDate": "2026-01-01", "calendarEndDate": "2026-12-31"}

and gets back, under the page-method wrapper key `d`, every meeting in that
range—upcoming ones included—each with its documents already attached as
`MeetingDocumentLink[]`. So one request covers a year, and no per-meeting page
needs fetching. That is also why this does not restrict itself to Council and
planning meetings the way per-meeting scrapers do: the committees cost
nothing extra.

A subclass supplies only the portal root.
"""

import json
import re
import urllib.parse
from datetime import date, datetime
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR

# Each document link carries a `Type` and a `Format` ('.pdf' or 'HTML'), and
# the types are not all agendas just because the word appears in them.
# Measured across Logan's 2019-2027 calendar:
#
#   Agenda               the agenda as published before the meeting
#   Merged               "Revised Agenda": the agenda with an addendum folded in
#   PostAgenda           "Post-meeting package": the full agenda plus whatever
#                        was tabled on the day, published with the minutes
#   Addendum             a supplementary agenda—a second document, not the
#                        agenda
#   AgendaCover,         the cover page alone
#   MergedCover
#   PostMinutes          the minutes
#   AdditionalDocuments  anything else: signed copies of the minutes, notices
#                        of cancellation, attachments
#
# The plain agenda wins. The other two are fallbacks for meetings that never
# got one: Logan's 14 July 2026 Governance committee has only a PostAgenda,
# which still contains the whole agenda. Addenda and cover pages are never
# stored as the agenda.
_AGENDA_TYPES = ("Agenda", "Merged", "PostAgenda")
_MINUTES_TYPES = ("PostMinutes",)

# AdditionalDocuments is a grab-bag, but two things in it are the papers
# themselves, and only its free-text `Title` says so:
#
# - The earliest meetings on a portal can carry their papers only as
#   uploads—Logan's five January 2020 meetings have "Ordinary Council Agenda
#   0768 - 29 January 2020", "Ordinary Council Minutes - 29 January 2020" and
#   the like, and nothing else.
# - The signed "Confirmed Minutes" scan, attached to the meeting it records
#   once the next meeting has confirmed it. Logan's 23 November 2022 Council
#   has that and no PostMinutes.
#
# So these are fallbacks, used only when no typed document exists. Anything
# naming an attachment, addendum or tabled item is not the paper itself
# ("Updated or Additional Attachments - Item 8 - Mayoral Minute ..." names a
# minute but is an attachment), nor is a notice of cancellation.
_UPLOADED_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_UPLOADED_MINUTES = re.compile(r"\bmin+utes\b", re.IGNORECASE)  # "minnutes" too
_NOT_THE_PAPER = re.compile(
    r"attachment|addend|supplement|tabled|updated|cover|notice|released",
    re.IGNORECASE,
)
# Titles that name a date: "28 January 2026", "09 December 2020", "15-07-2026",
# "29-11-2023". A confirmed-minutes title naming some other day is filed on
# the wrong meeting and is not used.
_TITLE_DATE = re.compile(
    r"\b(\d{1,2})[-\s](\d{1,2}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"[a-z]*[-\s](\d{4})\b",
    re.IGNORECASE,
)
_MONTHS = {
    m: i
    for i, m in enumerate(
        "jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1
    )
}

# eScribe pads the venue into a <br/>-separated block.
_LINE_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)


class EScribeScraper(BaseScraper):
    # eScribe names a meeting after its meeting *type*, and a council that
    # renames a committee renames the type, so every past meeting of it takes
    # the new name too—the calendar, MeetingName and Meeting.aspx's <title>
    # alike keep no history. A subclass whose council has done this maps
    # each current name to the date of the first meeting held under it and
    # the name before then: {current: (first_date_iso, former)}. The dates
    # come from the papers themselves, whose cover pages print the name the
    # committee had at the time.
    former_names: dict[str, tuple[str, str]] = {}

    def __init__(self, council_name: str, state: str, portal_url: str):
        self.portal_url = portal_url.rstrip("/")
        super().__init__(council_name, state, self.portal_url)

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(years_filter)
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _calendar(self, year: int) -> Optional[list[dict]]:
        """Every meeting the portal lists for one calendar year.

        A year at a time rather than one range for the whole history: it is
        what production asks for anyway (a single year), and it keeps each
        response small on a portal whose limits we have not measured.
        """
        url = f"{self.portal_url}/MeetingsCalendarView.aspx/GetCalendarMeetings"
        try:
            body = self.fetcher.fetch_with_requests(
                url,
                method="POST",
                json={
                    "calendarStartDate": f"{year}-01-01",
                    "calendarEndDate": f"{year}-12-31",
                },
            )
            return json.loads(body)["d"]
        except Exception as e:
            self.logger.warning(
                f"{self.council_name}: could not read the eScribe calendar for "
                f"{year}: {e}"
            )
            return None

    def _uploaded(self, links: list[dict], label: re.Pattern, day: date) -> dict:
        """The PDF an AdditionalDocuments upload holds for the agenda or the
        minutes, if one is plainly that—see _UPLOADED_AGENDA."""
        for link in links:
            title = link.get("Title") or ""
            if (
                link.get("Type") != "AdditionalDocuments"
                or link.get("Format", "").lower() != ".pdf"
                or not link.get("Url")
                or not label.search(title)
                or _NOT_THE_PAPER.search(title)
            ):
                continue
            named = [_title_date(m) for m in _TITLE_DATE.finditer(title)]
            named = [d for d in named if d]
            if named and day not in named:
                continue
            return {"pdf": urllib.parse.urljoin(self.portal_url + "/", link["Url"])}
        return {}

    def _name(self, meeting: dict, day: date) -> Optional[str]:
        name = (meeting.get("MeetingName") or meeting.get("MeetingType") or "").strip()
        if name in self.former_names:
            renamed_on, former = self.former_names[name]
            if day.isoformat() < renamed_on:
                return former
        return name or None

    def _document(self, links: list[dict], types: tuple[str, ...]) -> dict:
        """The PDF and HTML renditions of the first document type present.

        Both renditions are taken from the same type, so a record never pairs
        one document's PDF with a different document's HTML.
        """
        for doc_type in types:
            found = {}
            for link in links:
                if link.get("Type") != doc_type or not link.get("Url"):
                    continue
                url = urllib.parse.urljoin(self.portal_url + "/", link["Url"])
                kind = "pdf" if link.get("Format", "").lower() == ".pdf" else "html"
                found.setdefault(kind, url)
            if found:
                return found
        return {}

    @staticmethod
    def _location(meeting: dict) -> Optional[str]:
        """The full venue, which `Description` spells out and `Location`
        abbreviates to the room name."""
        description = meeting.get("Description") or ""
        lines = [
            BeautifulSoup(line, "html.parser").get_text(" ", strip=True)
            for line in _LINE_BREAK.split(description)
        ]
        lines = [line for line in lines if line]
        if lines:
            return ", ".join(lines)
        return meeting.get("Location") or None

    def _meeting(self, meeting: dict) -> Optional[ScraperReturn]:
        # StartDate is the portal's local wall-clock time, "2026/07/15
        # 10:00:00", with no offset to convert.
        start = datetime.strptime(meeting["StartDate"], "%Y/%m/%d %H:%M:%S")

        links = meeting.get("MeetingDocumentLink") or []
        agenda = self._document(links, _AGENDA_TYPES) or self._uploaded(
            links, _UPLOADED_AGENDA, start.date()
        )
        minutes = self._document(links, _MINUTES_TYPES) or self._uploaded(
            links, _UPLOADED_MINUTES, start.date()
        )
        if not agenda and not minutes:
            # Scheduled but not yet papered, or cancelled—a cancelled
            # meeting keeps only its notice of cancellation.
            return None

        # The calendar's own `Url` (MeetingsCalendarView.aspx/Meeting?Id=...)
        # answers 404 to a plain GET; Meeting.aspx is the page the portal
        # actually serves for a meeting.
        webpage_url = f"{self.portal_url}/Meeting.aspx?" + urllib.parse.urlencode(
            {"Id": meeting["ID"], "lang": "English"}
        )

        agenda_url = agenda.get("pdf")
        minutes_url = minutes.get("pdf")
        return ScraperReturn(
            name=self._name(meeting, start.date()),
            date=start.date().isoformat(),
            time=start.strftime("%I:%M %p").lstrip("0"),
            webpage_url=webpage_url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            agenda_html_url=agenda.get("html"),
            minutes_html_url=minutes.get("html"),
            download_url=agenda_url or minutes_url,
            location=self._location(meeting),
        )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        found: list[tuple[str, ScraperReturn]] = []
        years = self._wanted_years()
        failed = []
        for year in years:
            meetings = self._calendar(year)
            if meetings is None:
                failed.append(year)
                continue
            for meeting in meetings:
                # The range is inclusive at both ends; keep each meeting in the
                # one year it belongs to.
                if not meeting.get("StartDate", "").startswith(f"{year}/"):
                    continue
                record = self._meeting(meeting)
                if record:
                    found.append((meeting["StartDate"], record))

        # The calendar returns meetings in no stable order. StartDate is
        # zero-padded, so it sorts chronologically as a string.
        found.sort(key=lambda pair: (pair[0], pair[1].name or ""))
        results = [record for _, record in found]

        if failed and len(failed) == len(years):
            # Every request failed, so an empty list would read downstream as
            # "this council held no meetings" rather than "the scraper is
            # broken". One bad year among several is only a warning.
            raise RuntimeError(
                f"{self.council_name}: every eScribe calendar request failed "
                f"({', '.join(map(str, failed))})"
            )

        if not results:
            self.logger.warning(f"{self.council_name} scraper found no meetings")
        else:
            self.logger.info(
                f"{self.council_name} scraper found {len(results)} meetings"
            )
        return results


def _title_date(match: re.Match):
    """The date a _TITLE_DATE match names, or None if it is not a real one."""
    day, month, year = match.groups()
    month = int(month) if month.isdigit() else _MONTHS[month[:3].lower()]
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None
