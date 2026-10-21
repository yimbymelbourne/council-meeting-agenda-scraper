import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.alyka import find_date
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.belyuen.nt.gov.au"
_LISTING_URL = f"{_BASE_URL}/council-meetings"

# A SITE123 site. The listing links a page per meeting, titled with the
# meeting and its date ("OCM - 29th September 2026", "SFM - 31 March 2026",
# "Council Meeting - 28 Mar 2022"), and each page links its files on
# SITE123's CDN under their original names: "OCM Agenda 20260929.pdf",
# "20260929 Minutes of September Ordinary Council Meeting_Unconfirmed.pdf",
# alongside the meeting notice, the month's finance report and policies
# up for review. Papers are picked out by name.
#
# Every meeting costs a request, about 13 in a production year. Committee
# meetings are on a separate listing and are not read. robots.txt disallows
# only SITE123's /versions/2/include/ and /versions/2/wizard/.
#
# The title is the date the meeting sat. File names carry the date the
# paper was prepared for, which is often not it: the February 2023 meeting
# "(HELD 9th March 2023)" has `20230228 OCM Agenda.pdf`, and the April 2023
# meeting, titled 18 May 2023, has `20230427 Confirmed OCM Minutes.pdf`.
# Two title forms need more than the leading date:
#
#   - "OCM - 25th August 2026 (01/09/2026)": the meeting moved, and the date
#     in brackets is when it sat (its minutes: "HELD: September 1st 2026").
#   - "Council Meeting - 26 Oct 2020 RESCHEDULED": the page keeps the
#     original date and holds the papers of the meeting as it was finally
#     held, `20201102 Draft OCM Agenda.pdf` and minutes "HELD 2nd November
#     2020". When the agenda and minutes file names agree on another day,
#     that day is the meeting's. A postponed meeting with no minutes did not
#     sit that day, and a cancelled one not at all, so neither is returned.

_MOVED_TO = re.compile(r"\((\d{1,2})/(\d{1,2})/(\d{4})\)")
_RESCHEDULED = re.compile(r"reschedul|postpon", re.IGNORECASE)
_CANCELLED = re.compile(r"cancel", re.IGNORECASE)
_COMPACT_DATE = re.compile(r"(?<!\d)(20\d\d)(\d\d)(\d\d)(?!\d)")
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
_MINUTES = re.compile(r"minutes", re.IGNORECASE)
_NOT_A_PAPER = re.compile(r"notice|attachment", re.IGNORECASE)
_CONFIRMED = re.compile(r"(?<!un)confirmed", re.IGNORECASE)


def _meeting_type(title: str) -> Optional[str]:
    prefix = title.split(" - ", 1)[0].strip().upper()
    if prefix.startswith("SFM"):
        return "Special Finance Meeting"
    if prefix.startswith("SCM") or prefix.startswith("SPECIAL"):
        return "Special Council Meeting"
    if prefix.startswith("OCM") or prefix.startswith("COUNCIL MEETING"):
        return "Ordinary Council Meeting"
    return None


def _compact_date(name: str) -> Optional[datetime.date]:
    match = _COMPACT_DATE.search(name)
    if not match:
        return None
    try:
        return datetime.date(*(int(g) for g in match.groups()))
    except ValueError:
        return None


@register_scraper
class BelyuenScraper(BaseScraper):
    # One production year measured 25 s from home (13 requests).
    expected_seconds = 26.0

    def __init__(self):
        super().__init__("belyuen", "NT", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _get(self, url: str) -> str:
        """Fetch a page, retrying once when the server drops the connection.

        The host (Caddy) closed a kept-alive connection without answering
        once in about ninety page loads while this was recorded, and that
        alone would fail the council for the night. One retry, then the
        error stands.
        """
        try:
            return self.fetcher.fetch_with_requests(url)
        except requests.ConnectionError as error:
            self.logger.warning(f"{self.council_name}: {url} dropped ({error}); retrying once")
            self.fetcher.sleep(5)
            return self.fetcher.fetch_with_requests(url)

    def _listing(self) -> list[tuple[str, str, datetime.date]]:
        """(title, page URL, title date) per meeting page."""
        soup = BeautifulSoup(self._get(_LISTING_URL), "html.parser")
        meetings = {}
        for link in soup.find_all("a", href=True):
            href = link["href"].strip()
            if not href.startswith("/council-meetings/"):
                continue
            title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            found = find_date(title)
            if not found or _meeting_type(title) is None:
                continue
            meetings.setdefault(urljoin(_BASE_URL, href), (title, found[0]))
        if not meetings:
            raise ValueError(f"{self.council_name}: no meeting pages linked from {_LISTING_URL}")
        return [(title, url, date) for url, (title, date) in meetings.items()]

    @staticmethod
    def _papers(html: str) -> list[tuple[str, str, str]]:
        """(kind, file name, URL) for each agenda or minutes on a page."""
        papers = []
        seen = set()
        for link in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            url = link["href"].strip()
            if not url.lower().endswith(".pdf") or url in seen:
                continue
            seen.add(url)
            name = link.get_text(" ", strip=True) or unquote(url.rsplit("/", 1)[-1])
            if _NOT_A_PAPER.search(name):
                continue
            if _MINUTES.search(name):
                papers.append(("minutes", name, url))
            elif _AGENDA.search(name):
                papers.append(("agenda", name, url))
        return papers

    @staticmethod
    def _held_on(title: str, title_date: datetime.date, papers) -> Optional[datetime.date]:
        moved = _MOVED_TO.search(title)
        if moved:
            day, month, year = (int(g) for g in moved.groups())
            try:
                return datetime.date(year, month, day)
            except ValueError:
                return title_date
        if not _RESCHEDULED.search(title):
            return title_date
        if not any(kind == "minutes" for kind, _, _ in papers):
            return None
        named = {_compact_date(name) for _, name, _ in papers}
        if len(named) == 1 and None not in named:
            return named.pop()
        return title_date

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        results = []
        # Every request is left to raise: a page that fails is a meeting
        # missing, and the listing failing is all of them.
        for title, url, title_date in self._listing():
            if _CANCELLED.search(title):
                continue
            # A meeting moved a week or two can cross into the next year, so
            # a December page is read for the January after it too.
            if not ({title_date.year, (title_date + datetime.timedelta(days=14)).year} & wanted):
                continue
            papers = self._papers(self._get(url))
            date = self._held_on(title, title_date, papers)
            if date is None or date.year not in wanted:
                continue

            agenda_url = next((u for kind, _, u in papers if kind == "agenda"), None)
            minutes = [(n, u) for kind, n, u in papers if kind == "minutes"]
            minutes_url = next(
                (u for n, u in minutes if _CONFIRMED.search(n)),
                minutes[0][1] if minutes else None,
            )
            if not agenda_url and not minutes_url:
                continue
            results.append(
                ScraperReturn(
                    name=_meeting_type(title),
                    date=date.isoformat(),
                    time=None,
                    webpage_url=url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        results.sort(key=lambda r: r.date)
        if not results:
            # The one legitimate empty answer: a run for the current year in
            # its first quarter, before any of its papers are up (or for a
            # later year). Anything else means the site changed, and [] would
            # be recorded as a successful scrape.
            this_year = clock.current_year()
            if all(y > this_year or (y == this_year and clock.today().month <= 3) for y in wanted):
                self.logger.warning(f"{self.council_name}: no meetings published yet for {sorted(wanted)}")
            else:
                raise RuntimeError(f"{self.council_name}: found no meetings for {sorted(wanted)}")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
