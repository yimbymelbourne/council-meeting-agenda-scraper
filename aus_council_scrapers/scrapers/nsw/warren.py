import calendar
import re
from collections import defaultdict
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.pdf_dates import meeting_date_from_papers

_BASE_URL = "https://www.warren.nsw.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/meetings"

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTH = re.compile(r"\b(" + "|".join(_MONTHS) + r")\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(20\d{2})\b")
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_BUSINESS_PAPER = re.compile(r"\bbusiness\s+paper", re.IGNORECASE)
_PART = re.compile(r"\bpart\s*(\d+)", re.IGNORECASE)
_EXTRAORDINARY = re.compile(r"extra\s*-?\s*ordinary", re.IGNORECASE)

# The cover is the last thing Acrobat added to each business paper, so it
# sits at the end of a 5-13 MB file and the whole file is read to see it.
# That happens only for a meeting with no minutes yet, one a night; the
# minutes are a few hundred KB with their heading in the first bytes.
_FULL_LIMIT = 16 * 1024 * 1024


@register_scraper
class WarrenScraper(BaseScraper):
    """Warren Shire Council: one page, an accordion per year.

    Each link is labelled by year and month only ("MEETING 2026 January
    Business Paper", "MEETING 2026 January Minutes"); filenames sometimes
    have a day and sometimes a different one ("Meeting 2025 June Minutes"
    is "June 26 Minutes.pdf"), so neither is read for the day. The day
    comes from the papers' first page: the minutes' heading ("ORDINARY
    MEETING MINUTES Thursday 22nd January 2026") or, before the minutes
    are up, the business paper's cover. Supplementary reports and parts 2-4
    of a split business paper are not the agenda. A meeting neither paper
    dates is left out and logged.
    """

    # One listing request, then one PDF read per meeting in the year. With
    # the shared 2 s per-host spacing, about 25 s for a production year.
    expected_seconds = 25.0

    def __init__(self):
        super().__init__("warren", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        html = self.fetcher.fetch_with_requests(_LISTING_URL)
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select("ul.council-meetings li.council-meetings__item")
        if not items:
            raise RuntimeError(f"warren: no year accordions on {_LISTING_URL}")

        # (year, month, name) -> {"agenda": (part, url), "minutes": url}
        meetings: dict[tuple, dict] = defaultdict(dict)
        for item in items:
            title = item.select_one("a.accordion-title")
            accordion_year = _YEAR.search(title.get_text() if title else "")
            for a in item.select("a[href]"):
                if a is title or ".pdf" not in a["href"].lower():
                    continue
                label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
                month = _MONTH.search(label)
                year = _YEAR.search(label) or accordion_year
                if not month or not year:
                    continue
                key = (
                    int(year.group(1)),
                    _MONTHS[month.group(1).lower()],
                    (
                        "Extraordinary Meeting"
                        if _EXTRAORDINARY.search(label)
                        else "Ordinary Meeting"
                    ),
                )
                url = urljoin(_LISTING_URL, a["href"])
                if _MINUTES.search(label):
                    meetings[key].setdefault("minutes", url)
                elif (
                    _BUSINESS_PAPER.search(label)
                    and "supplementary" not in label.lower()
                ):
                    part = _PART.search(label)
                    part = int(part.group(1)) if part else 1
                    best = meetings[key].get("agenda")
                    if best is None or part < best[0]:
                        meetings[key]["agenda"] = (part, url)

        results = []
        undated = []
        for (year, month, name), papers in sorted(meetings.items()):
            if year not in wanted:
                continue
            agenda = papers.get("agenda", (None, None))[1]
            minutes = papers.get("minutes")
            date = meeting_date_from_papers(
                self.fetcher,
                [minutes, agenda],
                year,
                month,
                full_limit=_FULL_LIMIT,
                logger=self.logger,
            )
            if date is None:
                undated.append(f"{calendar.month_name[month]} {year} {name}")
                continue
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda,
                    minutes_url=minutes,
                    download_url=agenda or minutes,
                )
            )
        if undated:
            self.logger.warning(f"warren: left out, no day on either paper: {undated}")
        if not results:
            if not meetings:
                raise RuntimeError(f"warren: no meeting papers on {_LISTING_URL}")
            today = clock.today()
            if undated or not (wanted == {today.year} and today.month <= 3):
                raise RuntimeError(
                    f"warren: no dated meeting in {sorted(wanted)}; undated: {undated}"
                )
            self.logger.warning(f"warren: no papers for {sorted(wanted)} yet")
        return results
