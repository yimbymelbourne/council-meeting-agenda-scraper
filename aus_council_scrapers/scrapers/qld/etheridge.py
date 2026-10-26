import datetime
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.etheridge.qld.gov.au"
_YEAR_URL = _BASE_URL + "/Council/Meetings/{year}-General-Meetings"

# An OpenCities site, but not its meetings module, so OpenCitiesMeetingsScraper
# does not apply: each year is an ordinary content page
# (/Council/Meetings/<year>-General-Meetings, 2015 onwards) listing a
# sub-page per meeting as div.list-item-container cards, and each meeting
# page links its papers under "Related Information" with descriptive link
# text ("Open Session Agenda - 15 July 2026 (PDF, 15MB)", "Confirmed General
# Meeting Minutes - 15 July 2026 (PDF, 604KB)"), or, on pages from before
# mid-2025, under a heading per paper with every link labelled "Download
# PDF". The closed-session agenda is a cover page only, and "Download All"
# is a zip; neither is read.
#
# The year page lists the whole year's calendar in advance, so a meeting
# page is fetched only once the meeting is near enough to have an agenda;
# that keeps a production year to the year page and about a dozen meetings.
_AGENDA_DAYS_AHEAD = 21

_DATE = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+20\d\d\b",
    re.IGNORECASE,
)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_NOT_AGENDA = re.compile(r"closed|confidential|late|attachment|supplementary", re.I)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_UNCONFIRMED = re.compile(r"unconfirmed", re.IGNORECASE)
_TYPE = re.compile(r"Type:\s*([A-Za-z ]+?Meeting)", re.IGNORECASE)
# An agenda the council filed under the wrong heading: 17 May 2023's
# open_session_agenda___may_2023.pdf sits under "Closed Session Agenda - May
# 2023". The file name is the better witness there.
_OPEN_AGENDA_FILE = re.compile(r"open[_-]*(?:session[_-]*)?agenda", re.IGNORECASE)

# A day and month in a paper's file name ("..._18th_december_2024_amended_
# 23_01_25.pdf", "open_agenda___21_may_2025.pdf", "..._29may2025.pdf",
# "..._minutes_23_june.pdf"). The first one is the meeting's; later ones are
# amendment stamps.
_FILE_DATE = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[_\- ]*"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    r"(?:[_\- ]*(20\d\d)(?!\d))?",
    re.IGNORECASE,
)
# How far a file name's date may sit from the card's and still be read as
# the same meeting with the card mistyped, rather than another meeting's
# paper.
_FILE_DATE_WINDOW_DAYS = 14

# A year's page appears only once the council makes it (2027's still 404s in
# October 2026), so early January may have none. An empty or missing
# current year is an error only once this much of it has passed, the rule
# CraftMeetingsModuleScraper uses.
_NEW_YEAR_GRACE_DAYS = 90


def _owed_papers(year: int) -> bool:
    """Whether a year has run long enough that it must have papers."""
    today = clock.today()
    return year < today.year or (
        year == today.year
        and (today - datetime.date(year, 1, 1)).days >= _NEW_YEAR_GRACE_DAYS
    )


def _file_date(url, year: int):
    if not url:
        return None
    match = _FILE_DATE.search(url.rsplit("/", 1)[-1])
    if not match:
        return None
    day, month, stated_year = match.groups()
    try:
        return parse_date(f"{day} {month} {stated_year or year}").date()
    except (ValueError, OverflowError):
        return None


def _reconciled_date(card: datetime.date, agenda_url, minutes_url) -> datetime.date:
    """The card's date, unless the papers' file names agree on another.

    The card for the December 2024 meeting says 11 December; the agenda's
    first page says Wednesday 18 December 2024, and so do the minutes and
    their file name (confirmed_general_meeting_minutes___18th_december_2024_
    amended_23_01_25.pdf). Of the 2020-2026 meetings it is the only one
    whose file names disagree with its card.
    """
    stated = {
        date
        for date in (
            _file_date(agenda_url, card.year),
            _file_date(minutes_url, card.year),
        )
        if date and abs((date - card).days) <= _FILE_DATE_WINDOW_DAYS
    }
    if len(stated) == 1 and card not in stated:
        return stated.pop()
    return card


@register_scraper
class EtheridgeScraper(BaseScraper):
    # One production year (2026), measured 20 Oct 2026 from a home IP:
    # 13 requests, 24 s at the default FETCH_DELAY. Orders dispatch only;
    # see BaseScraper.expected_seconds.
    expected_seconds = 24

    def __init__(self):
        super().__init__("etheridge", "QLD", _BASE_URL)

    def _new_year_only(self) -> bool:
        """True when no wanted year is yet old enough to be owed papers."""
        return not any(_owed_papers(year) for year in self._wanted_years())

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(years_filter)
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _cards(self, year: int) -> list[tuple]:
        """(date, meeting type or None, page URL) for each meeting listed."""
        url = _YEAR_URL.format(year=year)
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        if not soup.select("div.list-item-container"):
            # Each year page lists the whole year's calendar in advance (the
            # 2026 page has 14 cards, including December's), so a page with
            # no cards is a markup change, not a quiet year.
            raise RuntimeError(f"{self.council_name}: no meeting cards on {url}")
        cards = []
        for card in soup.select("div.list-item-container"):
            link = card.find("a", href=True)
            if not link:
                continue
            text = re.sub(r"\s+", " ", card.get_text(" ", strip=True))
            match = _DATE.search(text)
            if not match:
                continue
            date = parse_date(match.group(), fuzzy=True).date()
            stated = _TYPE.search(text)
            title = card.find(class_="list-item-title")
            title_text = title.get_text(" ", strip=True) if title else ""
            if stated:
                meeting = stated.group(1).strip()
            elif re.search(r"special", title_text, re.I):
                meeting = "Special Meeting"
            elif re.search(r"general meeting", title_text, re.I):
                meeting = "General Meeting"
            else:
                meeting = None
            if re.search(r"budget", title_text, re.I):
                meeting = "Special Budget Meeting"
            cards.append((date, meeting, urljoin(url, link["href"])))
        return cards

    def _papers(self, url: str) -> tuple:
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        heading = soup.find("h1")
        agenda = minutes = None
        minutes_rank = None
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "/files/assets/" not in href or not href.lower().endswith(".pdf"):
                continue
            text = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            file_name = href.rsplit("/", 1)[-1]
            if not (_MINUTES.search(text) or _AGENDA.search(text)):
                # Pages before mid-2025 put each file under its own heading
                # ("Open Session Agenda", "Confirmed Minutes January") and
                # label every link "Download PDF (13MB)".
                heading_above = link.find_previous("h2")
                if heading_above:
                    text = heading_above.get_text(" ", strip=True)
            if _MINUTES.search(text):
                rank = 1 if _UNCONFIRMED.search(text) else 0
                if minutes is None or rank < minutes_rank:
                    minutes, minutes_rank = urljoin(url, href), rank
            elif _AGENDA.search(text) and (
                not _NOT_AGENDA.search(text)
                or (
                    _OPEN_AGENDA_FILE.search(file_name)
                    and not _NOT_AGENDA.search(file_name)
                )
            ):
                agenda = agenda or urljoin(url, href)
        return (heading.get_text(" ", strip=True) if heading else ""), agenda, minutes

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        horizon = clock.today() + datetime.timedelta(days=_AGENDA_DAYS_AHEAD)
        results, errors = [], []
        for year in self._wanted_years():
            if year > horizon.year:
                continue
            try:
                cards = self._cards(year)
            except Exception as e:
                self.logger.warning(f"{self.council_name}: could not read {year}: {e}")
                # A year page that should exist and does not, or has no
                # cards, fails the council even when other years were read.
                if _owed_papers(year):
                    raise
                errors.append(e)
                continue
            for card_date, meeting, url in cards:
                if card_date.year != year or card_date > horizon:
                    continue
                heading, agenda_url, minutes_url = self._papers(url)
                if not agenda_url and not minutes_url:
                    continue
                date = _reconciled_date(card_date, agenda_url, minutes_url)
                if meeting is None:
                    # 2020-2021 cards give only the date. The page heading
                    # and the file names say which meetings were special
                    # ("confirmed_special_meeting_minutes_23_june.pdf",
                    # "confirmed_budget_minutes.pdf", "..._spem_2020.pdf",
                    # the statutory post-election meeting).
                    evidence = " ".join([heading, agenda_url or "", minutes_url or ""])
                    if re.search(r"budget", evidence, re.I):
                        meeting = "Special Budget Meeting"
                    elif re.search(r"spem|post.election", evidence, re.I):
                        meeting = "Statutory Post Election Meeting"
                    elif re.search(r"special", evidence, re.I):
                        meeting = "Special Meeting"
                    else:
                        meeting = "General Meeting"
                results.append(
                    ScraperReturn(
                        name=meeting,
                        date=date.isoformat(),
                        time=None,
                        webpage_url=url,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )

        # Only a next year's page, or a new year's in its first weeks, gets
        # here having failed. Past that grace, a year with no papers at all
        # is a markup change: the council meets monthly.
        if not results and not self._new_year_only():
            if errors:
                raise errors[-1]
            raise RuntimeError(
                f"{self.council_name}: no agendas or minutes for "
                f"{self._wanted_years()}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
