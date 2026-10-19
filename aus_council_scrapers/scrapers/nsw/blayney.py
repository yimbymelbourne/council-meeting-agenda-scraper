import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup
from requests.utils import requote_uri

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.blayney.nsw.gov.au"
_CURRENT_URL = f"{_BASE_URL}/council/council-meetings/business-papers-minutes-and-recorded-live-streams"
_PRIOR_INDEX_URL = (
    f"{_CURRENT_URL}/prior-year-minutes-and-papers/prior-year-minutes-and-papers"
)

# Blayney's Kentico-style CMS keeps this year's papers on one page, as a table
# whose first row per meeting carries the date, and each earlier year on a page
# of its own linked from the prior-years index. The year pages are two widgets,
# nominally "Minutes" and "Business Papers", but the widget a link sits in is
# not reliable: the 2025 page heads both widgets "2024", the 27 August 2024
# agenda is filed under minutes, and the 21 December 2020 attachments under
# minutes too. So every document is classified by its own label instead, and
# the label's leading date ("22 September 2026 - Ordinary Council Meeting
# Agenda") says which meeting it belongs to.
#
# The year pages' URLs are irregular (2017's slug is garbled), so they are
# read from the index rather than built.
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
_LABEL_DATE = re.compile(
    r"(?<!\d)(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{4})",
    re.IGNORECASE,
)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b|business paper", re.IGNORECASE)
# Each of these is a second document for a meeting that already has its
# agenda: "Late Reports", "Late Attachments", "Addendum", "Report 18 -
# Addendum", "Late Mayoral Minute". None of them is the agenda.
_NOT_AGENDA = re.compile(
    r"attachment|late|addendum|supplementary|mayoral", re.IGNORECASE
)
_EXTRAORDINARY = re.compile(r"extra\s*-?\s*ordinary", re.IGNORECASE)
_YEAR_LINK = re.compile(r"^(\d{4}) Business Papers and Minutes$", re.IGNORECASE)


def _label_date(text: str) -> Optional[datetime.date]:
    match = _LABEL_DATE.search(text)
    if not match:
        return None
    day, month, year = match.groups()
    try:
        return datetime.date(int(year), _MONTHS[month[:3].lower()], int(day))
    except ValueError:
        return None


@register_scraper
class BlayneyScraper(BaseScraper):
    # The current-year page alone takes about 17 s to arrive (measured
    # 20 Oct 2026, three runs, 16.9–18.2 s), server time rather than
    # throttling, and it is the whole of a production run.
    expected_seconds = 18.0

    def __init__(self):
        super().__init__("blayney", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _documents(html: str, page_url: str) -> list[tuple[str, str]]:
        """(label, url) for every document link on a page, once each.

        The current page links each file twice, once from an icon with no
        text; the year pages put the label in the link's title.
        """
        soup = BeautifulSoup(html, "html.parser")
        documents = []
        seen = set()
        for anchor in soup.select("a.document[href]"):
            label = anchor.get("title") or anchor.get_text(" ", strip=True)
            url = requote_uri(urljoin(page_url, anchor["href"].strip()))
            if not label or url in seen:
                continue
            seen.add(url)
            documents.append((re.sub(r"\s+", " ", label), url))
        return documents

    def _year_pages(self, years: set[int]) -> dict[int, str]:
        html = self.fetcher.fetch_with_requests(_PRIOR_INDEX_URL)
        soup = BeautifulSoup(html, "html.parser")
        pages = {}
        for anchor in soup.find_all("a", href=True):
            match = _YEAR_LINK.match(anchor.get_text(" ", strip=True))
            if match and int(match.group(1)) in years:
                pages[int(match.group(1))] = urljoin(_PRIOR_INDEX_URL, anchor["href"])
        return pages

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        this_year = clock.current_year()

        # The current page carries this year and the tail of last year (the
        # December 2025 meeting sat there in October 2026), so it is read for
        # either. A production run for this year makes it the only request.
        pages: list[str] = []
        if any(year >= this_year - 1 for year in wanted):
            pages.append(_CURRENT_URL)
        earlier = {year for year in wanted if year < this_year}
        if earlier:
            year_pages = self._year_pages(earlier)
            missing = sorted(earlier - set(year_pages) - {this_year - 1})
            if missing:
                self.logger.warning(
                    f"{self.council_name}: no prior-year page for {missing}"
                )
            pages.extend(year_pages[year] for year in sorted(year_pages))

        meetings: dict[datetime.date, dict] = {}
        for page_url in pages:
            # Left to raise: a page that cannot be read is a year of meetings
            # silently missing, which must fail the council rather than
            # report a short list as success.
            html = self.fetcher.fetch_with_requests(page_url)
            for label, url in self._documents(html, page_url):
                filename = unquote(url.rsplit("/", 1)[-1])
                if _MINUTES.search(label):
                    kind = "minutes"
                elif _AGENDA.search(label) and not _NOT_AGENDA.search(label):
                    kind = "agenda"
                else:
                    continue
                date = _label_date(label)
                if date is None:
                    self.logger.warning(
                        f"{self.council_name}: cannot date {kind} {label!r} ({url}); skipped"
                    )
                    continue
                if date.year not in wanted:
                    continue
                meeting = meetings.setdefault(
                    date, {"page": page_url, "extraordinary": False}
                )
                # First link wins: the current upload is listed first.
                meeting.setdefault(kind, url)
                # Minutes labels often omit the type ("11 June 2024 -
                # Minutes") where the agenda or the file name carries it.
                if _EXTRAORDINARY.search(f"{label} {filename}"):
                    meeting["extraordinary"] = True

        results = []
        for date, meeting in sorted(meetings.items()):
            agenda_url = meeting.get("agenda")
            minutes_url = meeting.get("minutes")
            if not agenda_url and not minutes_url:
                continue
            results.append(
                ScraperReturn(
                    name=(
                        "Extraordinary Council Meeting"
                        if meeting["extraordinary"]
                        else "Ordinary Council Meeting"
                    ),
                    date=date.isoformat(),
                    time=None,
                    webpage_url=meeting["page"],
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
