import re

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.councilconnect import ELECTORS_NAMES, CouncilConnectScraper

# Albany's filenames carry the meeting's month and year as "feb25", "mar23",
# "3feb21".
_MONTH_YEAR = re.compile(
    r"(?<![a-z])(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[_ -]?"
    r"(\d{2})(?!\d)",
    re.IGNORECASE,
)


@register_scraper
class AlbanyScraper(CouncilConnectScraper):
    """City of Albany—documents on each meeting's own page.

    Council and electors' meetings only. The year listing also holds the
    Community and Corporate Services and Development and Infrastructure
    Services committees, which meet monthly and put their recommendations to
    the next Ordinary meeting, the OCM Agenda Advisory Committee, the audit
    and CEO review committees: about 35 meetings in 2025, each a request.
    Council and electors' meetings are ~14 a year.

    The Ordinary type's slug is `ordinary-council-meeting-(ocm)`. Its own
    year page 404s (with the brackets, encoded or dropped), so the all-types
    listing is read—four pages a year—and other types are skipped before
    their pages are fetched (`type_listings = False`).

    The upcoming page lists meetings without a date on the link, so every
    upcoming Council meeting on it costs a request (three in October 2026).

    The date field's time is often when the entry was saved: "1:59 PM" for
    the 6.00 pm meeting of 28 October 2025, "4:05 PM" for the 6.30 pm
    Special Electors' Meeting of 29 March 2021. A time off the quarter-hour
    is left blank.
    """

    meeting_types = {
        "ordinary-council-meeting-(ocm)": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
        "annual-meeting-of-electors": "Annual Meeting of Electors",
    }
    type_listings = False
    plausible_times_only = True
    # Five wordings in seven years: "Annual Electors' Meeting", "Annual
    # Meeting of Electors", "Special Electors' Meeting" and so on.
    canonical_names = ELECTORS_NAMES

    # On the quarter-hour, so the rule above keeps them, but still not the
    # start time. The 26 May 2020 agenda reads "Tuesday 26 May 2020 6.00pm"
    # (field: 8:30 AM). The 11 November 2020 special meeting (field: 5:00
    # PM) was called for "immediately after the Development and
    # Infrastructure Services Committee Meeting", and its minutes say it was
    # held at 6.20 pm; it has two pages (see _merge_duplicate_pages).
    corrections = {
        "https://www.albany.wa.gov.au/council-meetings/ordinary-council-meeting-(ocm)"
        "/ordinary-council-meeting-26-may-2020/493": {"time": "6:00 PM"},
        "https://www.albany.wa.gov.au/council-meetings/special-council-meeting"
        "/special-council-meeting/566": {"time": "6:20 PM"},
        "https://www.albany.wa.gov.au/council-meetings/special-council-meeting"
        "/special-council-meeting/567": {"time": "6:20 PM"},
    }

    # One production year, measured 20 Oct 2026 from a home IP: 30 s (16
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 30

    def __init__(self):
        super().__init__("albany", "WA", "https://www.albany.wa.gov.au")

    def _pick_documents(self, links, meeting_name=None, date=None):
        # An electors' meeting's page carries the previous electors'
        # meeting's minutes, for confirmation: the 5 February 2026 page has
        # "Electors Meeting_minutes_feb25" and nothing else, and 2023–2025
        # are the same. A document named for another month is that other
        # meeting's. Only for electors' meetings: the Ordinary meeting held
        # on 1 July 2025 was June's, and its own minutes are "jun25".
        #
        # Those minutes are kept aside and given to the meeting they name
        # (see scraper): the 27 March 2023, 20 March 2024 and 6 February 2025
        # meetings' minutes are only on the next year's page.
        if date is not None and re.search(r"elector", meeting_name or "", re.I):
            own = []
            for group, label, url in links:
                text = f"{label} {_filename(url)}"
                if not self._names_another_month(text, date):
                    own.append((group, label, url))
                elif re.search(r"minut", text, re.I) and url.lower().endswith(".pdf"):
                    for month_year in _MONTH_YEAR.findall(text.lower()):
                        self._other_electors_minutes.setdefault(
                            (month_year[0][:3], month_year[1]), []
                        ).append(url)
            links = own
        return super()._pick_documents(links, meeting_name, date)

    @staticmethod
    def _names_another_month(text: str, date) -> bool:
        named = {
            (month.lower(), year) for month, year in _MONTH_YEAR.findall(text.lower())
        }
        return (
            bool(named)
            and (date.strftime("%b").lower(), date.strftime("%y")) not in named
        )

    def scraper(self) -> list[ScraperReturn]:
        self._other_electors_minutes: dict[tuple[str, str], list[str]] = {}
        meetings = _merge_duplicate_pages(super().scraper())
        # A production night reads one year, so the minutes posted on next
        # year's page reach this year's meeting only in a run that reads
        # both years.
        for meeting in meetings:
            if meeting.minutes_url or "Electors" not in (meeting.name or ""):
                continue
            date = meeting.cleaned_date
            found = self._other_electors_minutes.get(
                (date.strftime("%b").lower(), date.strftime("%y")), []
            )
            # Confirmed over unconfirmed, as the base picks.
            found = sorted(found, key=lambda u: "unconfirm" in u.lower())
            if found:
                meeting.minutes_url = found[0]
        return meetings


def _merge_duplicate_pages(meetings: list[ScraperReturn]) -> list[ScraperReturn]:
    """One meeting where Albany made two pages for it.

    The 11 November 2020 and 20 December 2022 Special Council Meetings each
    have two pages (/566 and /567, /607 and /644): one with the agenda and
    unconfirmed minutes, one with the confirmed minutes, and the 2022 pair
    link the same agenda file. Both are kept as one meeting: the page with
    the confirmed minutes—whose time matches the agenda's 6.00 pm in
    2022—with the agenda from the other where it has none. Two same-day
    meetings with different agendas are left apart.
    """
    merged: list[ScraperReturn] = []
    for meeting in meetings:
        twin = next(
            (
                i
                for i, m in enumerate(merged)
                if (m.name, m.date) == (meeting.name, meeting.date)
                and (
                    not m.agenda_url
                    or not meeting.agenda_url
                    or _filename(m.agenda_url) == _filename(meeting.agenda_url)
                )
            ),
            None,
        )
        if twin is None:
            merged.append(meeting)
            continue
        earlier = merged[twin]
        keep, other = (
            (meeting, earlier)
            if _confirmed(meeting) and not _confirmed(earlier)
            else (earlier, meeting)
        )
        keep.agenda_url = keep.agenda_url or other.agenda_url
        keep.minutes_url = keep.minutes_url or other.minutes_url
        keep.download_url = keep.agenda_url or keep.minutes_url
        merged[twin] = keep
    return merged


def _filename(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def _confirmed(meeting: ScraperReturn) -> bool:
    return bool(meeting.minutes_url) and "unconfirm" not in meeting.minutes_url.lower()
