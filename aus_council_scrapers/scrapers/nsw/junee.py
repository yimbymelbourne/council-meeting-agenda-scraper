import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.junee.nsw.gov.au"
_MEETINGS_URL = f"{_BASE_URL}/council/council-meetings/"
_AGENDAS_URL = f"{_MEETINGS_URL}council-meeting-business-papers/"
_MINUTES_URL = f"{_MEETINGS_URL}council-meeting-minutes/"

# Junee publishes two WordPress pages, each a rolling twelve months of links:
# business papers ("2026 October Business Paper") and minutes ("2026 August
# Ordinary Meeting", "2026 March Extraordinary Meeting"). Older papers are
# taken down, and no archive page links them, so history starts about a year
# back from whenever the scraper runs.
#
# The labels give only a year and a month. The day comes from the filename:
# "Agenda-Business-Paper-20-October-2026-Ordinary-Council-Meeting.pdf",
# "2026-03-03_Extra.pdf", "Ordinary-Meeting-Minutes-18-August-2026.pdf".
# Three business papers have no day in their filename
# ("2026_Februar_Ordinary_Business_Paper.pdf"); each takes the date of that
# month's ordinary minutes, which do. One left without a day either way is
# left out rather than given a guessed one.
_LABEL = re.compile(r"^\s*(\d{4})\s+([A-Za-z]+)\b(.*)$")
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
_DAY_MONTH_YEAR = re.compile(
    r"(?<!\d)(\d{1,2})[\s_\-]+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    r"[\s_\-,]+(\d{4})",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"(?<!\d)(20\d\d)-(\d\d)-(\d\d)(?!\d)")
_EXTRAORDINARY = re.compile(r"extra", re.IGNORECASE)


def _filename_date(url: str) -> Optional[datetime.date]:
    filename = unquote(url.rsplit("/", 1)[-1])
    for year, month, day in _ISO_DATE.findall(filename):
        try:
            return datetime.date(int(year), int(month), int(day))
        except ValueError:
            continue
    for day, month, year in _DAY_MONTH_YEAR.findall(filename):
        try:
            return datetime.date(int(year), _MONTHS[month[:3].lower()], int(day))
        except ValueError:
            continue
    return None


@register_scraper
class JuneeScraper(BaseScraper):
    def __init__(self):
        super().__init__("junee", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _documents(self, url: str):
        """(year, month, extraordinary, document url, label) per labelled PDF."""
        # Not caught: losing either page loses half of every meeting, and the
        # council would be reported with agendas and no minutes, or neither.
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        documents = []
        for link in soup.find_all("a", href=True):
            href = urljoin(url, link["href"])
            if "/wp-content/uploads/" not in href or not href.lower().endswith(".pdf"):
                continue
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            match = _LABEL.match(label)
            if not match:
                continue
            month = _MONTHS.get(match.group(2)[:3].lower())
            if month is None:
                continue
            documents.append(
                (
                    int(match.group(1)),
                    month,
                    bool(_EXTRAORDINARY.search(f"{label} {href}")),
                    href,
                    label,
                )
            )
        if not documents:
            raise RuntimeError(f"{self.council_name}: no papers listed on {url}")
        return documents

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # (date, extraordinary) -> papers. Minutes first: every one of them
        # carries its day, so they settle the dates the business papers lack.
        meetings: dict[tuple[datetime.date, bool], dict[str, str]] = {}
        for year, month, extraordinary, url, label in self._documents(_MINUTES_URL):
            date = _filename_date(url)
            if date is None or (date.year, date.month) != (year, month):
                if year in wanted:
                    self.logger.warning(
                        f"{self.council_name}: no day for {label!r} ({url}); skipped"
                    )
                continue
            meetings.setdefault((date, extraordinary), {}).setdefault("minutes", url)

        for year, month, extraordinary, url, label in self._documents(_AGENDAS_URL):
            date = _filename_date(url)
            if date is None or (date.year, date.month) != (year, month):
                same_month = [
                    key
                    for key in meetings
                    if key[1] == extraordinary
                    and (key[0].year, key[0].month) == (year, month)
                ]
                if len(same_month) != 1:
                    if year in wanted:
                        self.logger.warning(
                            f"{self.council_name}: no day for {label!r} ({url}); skipped"
                        )
                    continue
                date = same_month[0][0]
            meetings.setdefault((date, extraordinary), {}).setdefault("agenda", url)

        results = []
        for (date, extraordinary), papers in sorted(meetings.items()):
            if date.year not in wanted:
                continue
            agenda_url = papers.get("agenda")
            minutes_url = papers.get("minutes")
            results.append(
                ScraperReturn(
                    name=(
                        "Extraordinary Council Meeting"
                        if extraordinary
                        else "Ordinary Council Meeting"
                    ),
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_AGENDAS_URL if agenda_url else _MINUTES_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            # The one empty answer that is not a fault: production asks for
            # the current year alone, and before March a small council may not
            # have posted its first paper of the year. Any other empty result
            # means the pages moved or stopped parsing, and returning [] would
            # read downstream as a successful night with no meetings.
            today = clock.today()
            if min(wanted) > today.year or (
                min(wanted) == today.year and today.month < 3
            ):
                self.logger.warning(
                    f"{self.council_name}: no meetings published yet for "
                    f"{sorted(wanted)}"
                )
            else:
                raise RuntimeError(
                    f"{self.council_name}: no meetings with documents for "
                    f"{sorted(wanted)}; the pages may have changed"
                )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
