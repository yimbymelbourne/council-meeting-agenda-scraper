import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.ngaanyatjarraku.wa.gov.au"
# A CouncilConnect content page, not its meetings module: one h2 per year,
# each over a document-centre table of `/documents/<id>/<slug>` links. Those
# links answer with the PDF itself (no redirect into the robots-disallowed
# `/Profiles/shire/Assets/ModuleData/`), so they are emitted as they are.
_LISTING_URL = f"{_BASE_URL}/our-shire/council/agenda-and-minutes.aspx"
# The council's annual public notice of Ordinary Council Meeting dates, the
# only place a meeting's day is published. Every listing label is month-only
# ("June - Ordinary Council Meeting - Agenda"), and the date column beside it
# is the upload date, not the meeting. The notice lists only the coming
# dates ("For the remainder of 2025: Wednesday, 17 December 2025 For
# 2026 ..."), so when the council replaces it with next year's, the
# meetings it dated drop out, and a re-record will shrink the fixture.
_SCHEDULE_URL = f"{_BASE_URL}/our-shire/council/meetings-and-public-question-time.aspx"
# The same notice: "Ordinary Council Meetings ... will be held at 1pm in the
# Council Chambers, Tjulyuru Cultural and Civic Centre, Warburton Community".
_TIME = "1:00 PM"
_LOCATION = "Council Chambers, Tjulyuru Cultural and Civic Centre, Warburton Community"

_MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
_MONTHS = {name: i + 1 for i, name in enumerate(_MONTH_NAMES)}
_SCHEDULE_DATE = re.compile(
    r"(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+(\d{1,2})\s+([a-z]+)\s+(\d{4})",
    re.IGNORECASE,
)
# "<Month> - <Meeting> - <Document>", spaced loosely.
_LABEL = re.compile(r"^\s*([a-z]+)\s*-\s*(.+?)\s*$", re.IGNORECASE)
_ORDINARY = re.compile(r"^ordinary\s+(council\s+)?meeting\b", re.IGNORECASE)
# The agenda proper; "Late Agenda" and "Late Agenda Item" are separate
# supplementary papers, and "Attachments" a separate volume.
_AGENDA = re.compile(r"(?<!late )\bagenda\s*$", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_UNCONFIRMED = re.compile(r"unconfirmed", re.IGNORECASE)


@register_scraper
class NgaanyatjarrakuScraper(BaseScraper):
    def __init__(self):
        super().__init__("ngaanyatjarraku", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _schedule(self) -> dict[tuple[int, int], datetime.date]:
        """(year, month) to meeting date, for months with one scheduled meeting."""
        html = self.fetcher.fetch_with_requests(_SCHEDULE_URL)
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        by_month: dict[tuple[int, int], set[datetime.date]] = {}
        for day, month, year in _SCHEDULE_DATE.findall(text):
            month_number = _MONTHS.get(month.lower())
            if not month_number:
                continue
            try:
                date = datetime.date(int(year), month_number, int(day))
            except ValueError:
                continue
            by_month.setdefault((date.year, date.month), set()).add(date)
        return {key: dates.pop() for key, dates in by_month.items() if len(dates) == 1}

    @staticmethod
    def _ordinary_papers(html: str) -> dict[tuple[int, int], dict[str, str]]:
        """(year, month) to {"agenda": url, "minutes": url} for Ordinary meetings.

        Only Ordinary Council Meetings are read, because they are the only
        meetings the council publishes a day for. The page repeats the 2026
        section where 2019 should be, so a document already seen is skipped.
        """
        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        papers: dict[tuple[int, int], dict[str, str]] = {}
        for heading in soup.find_all("h2"):
            year_text = heading.get_text(strip=True)
            table = heading.find_next("table")
            if not re.fullmatch(r"\d{4}", year_text) or table is None:
                continue
            if table.find_previous("h2") is not heading:
                continue
            year = int(year_text)
            for anchor in table.find_all("a", href=True):
                url = urljoin(_BASE_URL, anchor["href"].strip())
                if url in seen:
                    continue
                seen.add(url)
                match = _LABEL.match(anchor.get_text(" ", strip=True))
                if not match or match.group(1).lower() not in _MONTHS:
                    continue
                rest = match.group(2)
                if not _ORDINARY.match(rest):
                    continue
                if _MINUTES.search(rest):
                    kind = "minutes"
                elif _AGENDA.search(rest):
                    kind = "agenda"
                else:
                    continue
                key = (year, _MONTHS[match.group(1).lower()])
                current = papers.setdefault(key, {})
                # Confirmed minutes over unconfirmed ones, where both are up.
                if kind not in current or (
                    kind == "minutes"
                    and _UNCONFIRMED.search(current["minutes_label"])
                    and not _UNCONFIRMED.search(rest)
                ):
                    current[kind] = url
                    current[f"{kind}_label"] = rest
        return {
            key: {k: v for k, v in docs.items() if k in ("agenda", "minutes")}
            for key, docs in papers.items()
        }

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Both left to raise: the listing holds every paper and the schedule
        # every date, so without either the council has no datable meeting.
        papers = self._ordinary_papers(self.fetcher.fetch_with_requests(_LISTING_URL))
        schedule = self._schedule()

        results = []
        undated: list[tuple[int, int]] = []
        for (year, month), docs in sorted(papers.items()):
            if year not in wanted or not docs:
                continue
            date: Optional[datetime.date] = schedule.get((year, month))
            if not date:
                # Never a guessed day: the notice only covers the coming
                # year, so the history before it is left out.
                undated.append((year, month))
                continue
            agenda_url = docs.get("agenda")
            minutes_url = docs.get("minutes")
            results.append(
                ScraperReturn(
                    name="Ordinary Council Meeting",
                    date=date.isoformat(),
                    time=_TIME,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                    location=_LOCATION,
                )
            )

        recent = [key for key in undated if key[0] >= clock.current_year()]
        if recent:
            # This year's meetings should all be on the notice; one missing
            # means the notice moved on or the meeting was added late.
            self.logger.warning(
                f"{self.council_name}: no scheduled date for ordinary meetings in "
                f"{recent}; left out"
            )
        if undated:
            self.logger.info(
                f"{self.council_name}: {len(undated)} month-only ordinary meetings "
                f"before the published schedule left out"
            )
        if not results:
            self.logger.warning(
                f"{self.council_name} found no dated meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
