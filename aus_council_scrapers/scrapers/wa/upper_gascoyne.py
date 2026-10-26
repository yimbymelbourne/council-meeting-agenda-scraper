import re
from dataclasses import replace
from urllib.parse import unquote, urlparse

from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_small_shires import (
    SmallShireCouncilConnectScraper,
)

# "minutes_august-2026-unconfirmed-(5-files-merged).pdf"
_FILE_MONTH = re.compile(
    r"(january|february|march|april|may|june|july|august|september|october"
    r"|november|december)[\s_-]+(\d{4})",
    re.IGNORECASE,
)
# "agenda-for-electors-meeting-2024-2025-(3-files-merged).pdf",
# "agenda-for-annual-electors-meeting-2020-21.pdf": the financial year an
# electors' meeting reports on. Its first year is kept.
_FILE_FINANCIAL_YEAR = re.compile(
    r"(?<!\d)((?:19|20)\d{2})-(?:(?:19|20)\d{2}|\d{2})(?!\d)"
)


@register_scraper
class UpperGascoyneScraper(SmallShireCouncilConnectScraper):
    """Shire of Upper Gascoyne—documents on each meeting's own page.

    Council and electors' meetings; the audit committee, filed as both
    "Audit Committee Meeting" and "Audit Meeting", is skipped by heading.
    Headings give the month only ("Ordinary Council Meeting September
    2026"); the full date comes from the page.

    Since mid 2026 the shire posts a meeting's unconfirmed minutes on the
    *next* meeting's page, as they go to that meeting for confirmation: the
    September 2026 page carries "Minutes_August 2026", and the August page
    "Minutes_July 2026", which the July page also has (checked by reading
    the August file: the meeting of 26 August 2026). So a minutes file
    whose name gives another month is moved to that month's meeting of the
    same name, if it has none of its own, and is dropped otherwise.

    The electors' meetings do the same, but their files name the financial
    year the meeting reports on, not a month. The 10 February 2026 page
    carries "minutes-for-electors-meeting-2023-2024-unconfirmed" beside its
    2024-2025 agenda: the same file as the 12 February 2025 meeting's minutes
    (3,642,398 bytes; page 1 reads "12th of February 2025"). So minutes
    whose financial year differs from their own page's agenda are treated the
    same way, matched to the meeting whose agenda names that year.
    """

    # One production year, measured 20 Oct 2026 from a home IP: 23 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 23

    def scraper(self) -> list[ScraperReturn]:
        meetings = super().scraper()
        # Two ways a meeting is named in a filename: its month and year, and
        # (electors' meetings) the financial year on its agenda. A minutes
        # file that names a different one is lifted off its page, then given
        # to the meeting it names if that meeting has no minutes of its own.
        strays = {}
        for i, meeting in enumerate(meetings):
            date = parse_date(meeting.date).date()
            month = self._minutes_month(meeting)
            if month and month != (date.year, date.month):
                strays[(meeting.name, "month", month)] = meeting.minutes_url
                meetings[i] = self._with_minutes(meeting, None)
                continue
            minutes_year = self._financial_year(meeting.minutes_url)
            agenda_year = self._financial_year(meeting.agenda_url)
            if minutes_year and agenda_year and minutes_year != agenda_year:
                strays[(meeting.name, "year", minutes_year)] = meeting.minutes_url
                meetings[i] = self._with_minutes(meeting, None)
        for i, meeting in enumerate(meetings):
            if meeting.minutes_url:
                continue
            date = parse_date(meeting.date).date()
            stray = strays.get(
                (meeting.name, "month", (date.year, date.month))
            ) or strays.get(
                (meeting.name, "year", self._financial_year(meeting.agenda_url))
            )
            if stray:
                self.logger.info(f"{stray} is {meeting.date}'s minutes")
                meetings[i] = self._with_minutes(meeting, stray)
        meetings = [m for m in meetings if m.agenda_url or m.minutes_url]
        # The base's check for an empty result runs before this filter.
        if not meetings:
            raise RuntimeError(
                f"{self.council_name}: every meeting found had only another "
                "meeting's minutes"
            )
        return meetings

    @staticmethod
    def _financial_year(url):
        if not url:
            return None
        filename = unquote(urlparse(url).path.rsplit("/", 1)[-1])
        match = _FILE_FINANCIAL_YEAR.search(filename)
        return int(match.group(1)) if match else None

    @staticmethod
    def _minutes_month(meeting: ScraperReturn):
        if not meeting.minutes_url:
            return None
        filename = unquote(urlparse(meeting.minutes_url).path.rsplit("/", 1)[-1])
        match = _FILE_MONTH.search(filename)
        if not match:
            return None
        return int(match.group(2)), parse_date(match.group(1)).month

    @staticmethod
    def _with_minutes(meeting: ScraperReturn, minutes_url) -> ScraperReturn:
        return replace(
            meeting,
            minutes_url=minutes_url,
            download_url=meeting.agenda_url or minutes_url,
        )

    def __init__(self):
        super().__init__("upper_gascoyne", "WA", "https://www.uppergascoyne.wa.gov.au")
