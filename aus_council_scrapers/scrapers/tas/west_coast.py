import datetime
import re
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.pdf_dates import meeting_date_from_papers
from aus_council_scrapers.wpfd import (
    WPFDFile,
    WPFDListing,
    WPFileDownloadScraper,
    find_date,
)

# West Coast Council (Queenstown, Strahan, Zeehan). One WP File Download
# category per month, and the ordinary meeting's files name only the month
# ("Agenda - March 2026", "Minutes - March 2026"). Special meetings name their
# day ("Agenda - Special Council Meeting 14 July 2026").
#
# The day of an ordinary meeting comes from the council's own published
# schedule: the council-meetings page lists every 2026 date under "2026
# Meeting Dates" ("Tuesday 24 March 2026", "Tuesday 14 July 2026 – Special
# Meeting", "Thursday 10 December 2026 (Annual General Meeting & Ordinary
# Council Meeting)"). A month's undated meeting takes the one scheduled date
# of its type in that month. With none or several, the day is read from the
# meeting's own papers (pdf_dates.py), agenda first, and only a day in that
# month is taken; failing that it is left out with a warning rather than
# given a guessed day. That is how the January 2026 AGM is dated: the
# schedule lists "Tuesday 27 January 2026" as an ordinary meeting only, and
# the AGM agenda gives its own day. A meeting moved after the schedule was
# published would carry the scheduled day.
#
# Every ordinary meeting depends on the schedule, so a year with undated
# meetings and no schedule entries fails the scrape rather than quietly
# returning only the specials. That covers a redesigned page, and early
# January, when a new month's papers may be up before the year's dates are.
#
# So only 2026 on is covered (`earliest_year`). The archive page (2020–2023)
# and the 2024–2025 categories, which the page lazy-loads over admin-ajax,
# are month titles throughout ("Aug-2020-Open-Minutes", "May 2025 - Agenda"),
# specials included, and no schedule for those years is published, so
# nothing there can be dated to the day and neither is fetched.
#
# A production year is two requests, the listing and the schedule page,
# plus a PDF read or two for a meeting the schedule does not date.
# nginx, no CDN. robots.txt disallows only /wp-admin/ (admin-ajax allowed).

# "2026 Meeting Dates"; also "Meeting Dates 2027" or "Meeting Dates for
# 2027", should next year's heading be worded the other way round.
_SCHEDULE_HEADING = re.compile(
    r"^\s*(?:20\d\d\s+(?:council\s+)?meeting\s+dates"
    r"|(?:council\s+)?meeting\s+dates\s*(?:for\s+|[-–:]\s*)?20\d\d)\s*$",
    re.IGNORECASE,
)


@register_scraper
class WestCoastTasScraper(WPFileDownloadScraper):
    listings = (
        WPFDListing(
            "https://www.westcoast.tas.gov.au/council/our-council/council-meetings/agenda-minutes-and-recordings/"
        ),
    )
    schedule_url = (
        "https://www.westcoast.tas.gov.au/council/our-council/council-meetings/"
    )
    earliest_year = 2026

    def __init__(self):
        super().__init__("west_coast", "TAS", "https://www.westcoast.tas.gov.au")
        self._schedule: Optional[list[tuple[datetime.date, set[str]]]] = None

    def scraper(self):
        # Read afresh on each run; the instance lives in the registry.
        self._schedule = None
        return super().scraper()

    def _read_schedule(self) -> list[tuple[datetime.date, set[str]]]:
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(self.schedule_url), "html.parser"
        )
        entries = []
        for label in soup.select(".jet-toggle__label-text"):
            if not _SCHEDULE_HEADING.match(label.get_text(" ", strip=True)):
                continue
            toggle = label.find_parent(class_="jet-toggle")
            for item in toggle.select(".jet-toggle__content li") if toggle else []:
                text = " ".join(item.get_text(" ", strip=True).split())
                date = find_date(text)
                if date is None:
                    continue
                kinds = set()
                if re.search(r"annual\s+general", text, re.IGNORECASE):
                    kinds.add("Annual General Meeting")
                if re.search(r"\bspecial\b", text, re.IGNORECASE):
                    kinds.add("Special Council Meeting")
                if not kinds or re.search(r"\bordinary\b", text, re.IGNORECASE):
                    kinds.add("Council Meeting")
                entries.append((date, kinds))
        return entries

    def undated_meeting_date(
        self, month: Optional[tuple[int, int]], name: str, files: list[WPFDFile]
    ) -> Optional[datetime.date]:
        if month is None:
            return None
        if self._schedule is None:
            self._schedule = self._read_schedule()
        year, month_number = month
        if not any(date.year == year for date, _ in self._schedule):
            # Not a single meeting's day missing (the January AGM) but the
            # whole year's: every ordinary meeting would be left out.
            raise ValueError(
                f"{self.council_name}: no {year} 'Meeting Dates' schedule on "
                f"{self.schedule_url}, so its month-only meetings cannot be dated"
            )
        scheduled = [
            date
            for date, kinds in self._schedule
            if (date.year, date.month) == (year, month_number) and name in kinds
        ]
        if len(scheduled) == 1:
            return scheduled[0]
        # Off the schedule: one meeting a year or so, a PDF read or two.
        papers = sorted(files, key=lambda f: f.kind != "agenda")
        return meeting_date_from_papers(
            self.fetcher,
            [f.url for f in papers],
            year,
            month_number,
            logger=self.logger,
        )
