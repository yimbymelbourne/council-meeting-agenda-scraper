import calendar
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.pdf_dates import meeting_date_from_pdf

_BASE_URL = "https://coolamon.nsw.gov.au"
_MEETINGS_URL = f"{_BASE_URL}/council-meetings"
_MINUTES_URL = f"{_BASE_URL}/council-minutes-recordings"

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTH = re.compile(r"(" + "|".join(_MONTHS) + r")", re.IGNORECASE)
# A month as a whole word in a file name or link ("businesspaper_may_2026"),
# so "mayor" is not May.
_MONTH_WORD = re.compile(
    r"(?<![a-z])(" + "|".join(_MONTHS) + r")(?![a-z])", re.IGNORECASE
)
_YEAR = re.compile(r"(20\d{2})(?!\d)")
_DAY_MONTH = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:st|nd|rd|th)?\s+(" + "|".join(_MONTHS) + r")", re.IGNORECASE
)
_EXTRAORDINARY = re.compile(r"extra\s*-?\s*ordinary", re.IGNORECASE)
# "businesspaper_october_2024.pdf", "Business Paper November 2026".
_BUSINESS_PAPER = re.compile(r"business[\s_-]*paper|agenda", re.IGNORECASE)
# "Council next meeting will be held on Thursday, 19 November 2026
# commencing at 3.00pm."
_NEXT_MEETING = re.compile(
    r"next meeting will be held on\s+(?P<date>.+?\d{4})\s+commencing at\s+"
    r"(?P<time>\d{1,2}(?:[.:]\d{2})?\s*[ap]\.?m)",
    re.IGNORECASE,
)


@register_scraper
class CoolamonScraper(BaseScraper):
    """Coolamon Shire Council: Squarespace, two pages.

    The minutes page lists every meeting's minutes by month ("October 2026
    Minutes", "Extraordinary Meeting August 2024 Minutes"), with recordings
    beside them. The day is read from the minutes' first page ("MINUTES OF
    THE ORDINARY MEETING ... HELD IN THE COUNCIL CHAMBERS, COOLAMON ON THE
    15 OCTOBER 2026"); minutes that do not give it are left out and logged.

    The council publishes only the next meeting's business paper, on the
    meetings page, under "Council next meeting will be held on Thursday,
    19 November 2026 commencing at 3.00pm." That meeting is emitted once the
    business paper is linked (a record needs a document). Past meetings
    have minutes only: their business papers are taken down, except one
    left behind in the October 2024 row of the minutes page
    ("businesspaper_october_2024.pdf", no link text), which is attached to
    that meeting by its file name.
    """

    # Two pages, then one PDF read per meeting in the year. Most minutes
    # files are 1-3 MB and are not readable from their first bytes, so a
    # production year downloads about 20 MB.
    expected_seconds = 40.0

    def __init__(self):
        super().__init__("coolamon", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _content(html: str):
        # The page body: text blocks and, for 2023 and earlier, accordion
        # blocks, but not the site's header and footer.
        soup = BeautifulSoup(html, "html.parser")
        return [soup.find("main") or soup]

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        results: dict[tuple, ScraperReturn] = {}

        undated = []
        listed = 0
        seen: set[tuple] = set()
        # (year, month) -> a business paper the minutes page still links.
        papers: dict[tuple, str] = {}
        links = [
            a
            for block in self._content(self.fetcher.fetch_with_requests(_MINUTES_URL))
            for a in block.find_all("a", href=True)
        ]
        if not any(".pdf" in a["href"].lower() for a in links):
            raise RuntimeError(f"coolamon: no minutes PDFs on {_MINUTES_URL}")
        for a in links:
            href = a["href"]
            label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
            path = href.lower().split("?")[0]
            if not path.endswith(".pdf"):
                continue
            if _BUSINESS_PAPER.search(f"{label} {path}"):
                month, year = _MONTH_WORD.search(path), _YEAR.search(path)
                if month and year and int(year.group(1)) in wanted:
                    month_number = _MONTHS[month.group(1).lower()]
                    papers[(int(year.group(1)), month_number)] = urljoin(
                        _MINUTES_URL, href
                    )
                continue
            # Other unlabelled links are second copies of the row's minutes.
            if not label:
                continue
            month, year = _MONTH.search(label), _YEAR.search(label)
            if not month or not year or "minutes" not in label.lower() + href.lower():
                continue
            year, month_number = int(year.group(1)), _MONTHS[month.group(1).lower()]
            if year not in wanted:
                continue
            listed += 1
            name = (
                "Extraordinary Meeting"
                if _EXTRAORDINARY.search(label)
                else "Ordinary Meeting"
            )
            if (year, month_number, name) in seen:
                continue
            seen.add((year, month_number, name))
            url = urljoin(_MINUTES_URL, href)
            date = meeting_date_from_pdf(
                self.fetcher, url, year, month_number, logger=self.logger
            )
            if date is None:
                undated.append(label)
                continue
            results[(date, name)] = ScraperReturn(
                name=name,
                date=date.isoformat(),
                time=None,
                webpage_url=_MINUTES_URL,
                agenda_url=None,
                minutes_url=url,
                download_url=url,
            )

        for (year, month_number), paper in papers.items():
            match = [
                r
                for (date, name), r in results.items()
                if (date.year, date.month) == (year, month_number)
                and name == "Ordinary Meeting"
            ]
            if len(match) == 1:
                match[0].agenda_url = paper
                match[0].download_url = paper
            else:
                self.logger.warning(
                    f"coolamon: business paper {paper} matches no single dated "
                    f"meeting; left out"
                )

        upcoming = self._next_meeting(wanted)
        if upcoming:
            key = (parse_date(upcoming.date).date(), upcoming.name)
            if key in results:
                # The page has not moved on yet; the minutes are up too.
                results[key].agenda_url = upcoming.agenda_url
                results[key].download_url = (
                    upcoming.agenda_url or results[key].minutes_url
                )
                results[key].time = upcoming.time
            else:
                results[key] = upcoming

        if undated:
            self.logger.warning(f"coolamon: left out, no day in the minutes: {undated}")
        if not results:
            # From 1 January until the year's first business paper is
            # linked (mid-February), the current year has nothing at all.
            # That is not a breakage. Minutes listed for the year that could
            # not be dated are.
            today = clock.today()
            if listed or not (wanted == {today.year} and today.month <= 3):
                raise RuntimeError(
                    f"coolamon: no dated meeting in {sorted(wanted)}; "
                    f"undated: {undated}"
                )
            self.logger.warning(f"coolamon: no papers for {sorted(wanted)} yet")
            return []
        return sorted(results.values(), key=lambda r: r.date, reverse=True)

    def _next_meeting(self, wanted: set[int]) -> Optional[ScraperReturn]:
        blocks = self._content(self.fetcher.fetch_with_requests(_MEETINGS_URL))
        text = re.sub(
            r"\s+", " ", " ".join(b.get_text(" ", strip=True) for b in blocks)
        )
        m = _NEXT_MEETING.search(text)
        if not m:
            raise RuntimeError(f"coolamon: no next meeting date on {_MEETINGS_URL}")
        date = parse_date(m.group("date"), fuzzy=True).date()
        if date.year not in wanted:
            return None
        agenda, said = None, ""
        for block in blocks:
            for a in block.find_all("a", href=True):
                said = f"{a.get_text(' ', strip=True)} {a['href']}"
                if a["href"].lower().split("?")[0].endswith(
                    ".pdf"
                ) and _BUSINESS_PAPER.search(said):
                    agenda = urljoin(_MEETINGS_URL, a["href"])
                    break
            if agenda:
                break
        if not agenda:
            self.logger.info(f"coolamon: no business paper yet for {date}")
            return None
        on_cover = meeting_date_from_pdf(
            self.fetcher, agenda, date.year, date.month, logger=self.logger
        )
        named = _MONTH_WORD.search(said)
        if on_cover is None and not (
            named and _MONTHS[named.group(1).lower()] == date.month
        ):
            # Neither the cover nor the link puts the paper in the meeting's
            # month: it may be the last meeting's paper, not yet taken down.
            self.logger.warning(
                f"coolamon: {agenda} gives no day in the month of the next "
                f"meeting ({date}); left out"
            )
            return None
        if on_cover and on_cover != date:
            self.logger.warning(
                f"coolamon: the page says the next meeting is {date}, its "
                f"business paper {on_cover}; using the business paper's"
            )
            date = on_cover
        return ScraperReturn(
            name="Ordinary Meeting",
            date=date.isoformat(),
            time=m.group("time").replace(".", ":"),
            webpage_url=_MEETINGS_URL,
            agenda_url=agenda,
            minutes_url=None,
            download_url=agenda,
        )
