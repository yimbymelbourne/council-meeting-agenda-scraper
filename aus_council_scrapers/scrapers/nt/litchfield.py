import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://litchfield.nt.gov.au"

# One archive page per year, `/your-council/council-meetings/archive/<year>`,
# including the current year with its latest agenda (the 19 October 2026
# meeting was on the 2026 archive page on the day). The main
# `/your-council/council-meetings` page lists the current and previous year,
# the same meetings as those two archive pages, so it is not fetched. A year
# with nothing published answers 200 with no meetings.
_YEAR_URL = _BASE_URL + "/your-council/council-meetings/archive/{year}"

# Each meeting is a `div.meeting-item`: a header with the date ("19 Oct
# 2026") and the meeting type ("Council Meeting", "Special Council Meeting",
# "Thorak Regional Cemetery Meeting"), then labelled lists—Agenda, Minutes,
# Attachments, Notes. The Agenda list also carries late agendas, late
# attachments, memoranda and individual reports, and the Minutes list
# "Resolutions Moved into Open", so the document is picked by its name.
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
_MINUTES = re.compile(r"minutes", re.IGNORECASE)
_NOT_A_PAPER = re.compile(
    r"late|attachment|memorandum|moved|supplementary|addendum", re.IGNORECASE
)
# Many hrefs are mangled into a relative path wrapping the real URL,
# `/index%2Ephp/https%3A//litchfield.nt.gov.au/sites/default/files/...pdf`,
# which 404s when joined to the site. The wrapped URL itself works.
_WRAPPED_URL = re.compile(r"https?://.*$")

# "16 August 2022", "21-May-2024". Compact dates (20240618) are not read; a
# document with no date it can be checked against simply passes.
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_FULL_DATE = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s_\-.]*"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s_\-.,]*(\d{4})",
    re.IGNORECASE,
)


def _document_url(href: str) -> str:
    unquoted = unquote(href)
    if "://" in unquoted and not unquoted.startswith("http"):
        match = _WRAPPED_URL.search(unquoted)
        if match:
            # Unquoting turned %20 into spaces; put them back.
            return match.group().replace(" ", "%20")
    return urljoin(_BASE_URL, href)


def _named_dates(url: str) -> set[datetime.date]:
    found = set()
    for day, month, year in _FULL_DATE.findall(unquote(url.rsplit("/", 1)[-1])):
        try:
            found.add(datetime.date(int(year), _MONTHS.index(month[:3].lower()) + 1, int(day)))
        except ValueError:
            pass
    return found


def _papers_disagree(date: datetime.date, urls: list[str]) -> bool:
    """True when every paper's file name dates it to some other meeting.

    The 2022 archive lists the 16 August 2022 meeting twice, the second time
    under "16 Oct 2022"—a Sunday, and no meeting was held—with both papers
    named "... 16 August 2022" (its minutes link is dead). The real 18
    October meeting is listed separately. A file name agrees if it names a
    date within a few days of the header or the same day and month, because
    the year is sometimes mistyped: the 28 January 2021 agenda is filed as
    "... 28 January 2020.pdf". A paper whose name carries no full date cannot
    disagree.
    """

    def agrees(named: set[datetime.date]) -> bool:
        return any(
            abs((d - date).days) <= 3 or (d.month, d.day) == (date.month, date.day)
            for d in named
        )

    named = [_named_dates(url) for url in urls]
    return bool(named) and all(n and not agrees(n) for n in named)


@register_scraper
class LitchfieldScraper(BaseScraper):
    def __init__(self):
        super().__init__("litchfield", "NT", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _pick(meeting, label: str, word: re.Pattern) -> Optional[str]:
        for block in meeting.select(".meeting-item__meta-data"):
            label_tag = block.select_one(".meeting-item__meta-data-label")
            if not label_tag or label_tag.get_text(strip=True) != label:
                continue
            for link in block.find_all("a", href=True):
                url = _document_url(link["href"])
                if not url.lower().endswith(".pdf"):
                    continue
                text = f"{link.get_text(' ', strip=True)} {unquote(url.rsplit('/', 1)[-1])}"
                if word.search(text) and not _NOT_A_PAPER.search(text):
                    return url
        return None

    def _parse_page(self, html: str, page_url: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for meeting in soup.select("div.meeting-item"):
            date_tag = meeting.select_one(".meeting-item__header-date")
            type_tag = meeting.select_one(".meeting-item__header-meeting-type")
            if not date_tag:
                continue

            agenda_url = self._pick(meeting, "Agenda", _AGENDA)
            minutes_url = self._pick(meeting, "Minutes", _MINUTES)
            if not agenda_url and not minutes_url:
                continue

            name = type_tag.get_text(" ", strip=True) if type_tag else ""
            result = ScraperReturn(
                name=name or "Council Meeting",
                date=date_tag.get_text(" ", strip=True),
                time=None,
                webpage_url=page_url,
                agenda_url=agenda_url,
                minutes_url=minutes_url,
                download_url=agenda_url or minutes_url,
            )
            papers = [url for url in (agenda_url, minutes_url) if url]
            if _papers_disagree(result.cleaned_date, papers):
                self.logger.warning(
                    f"{self.council_name}: skipping {result.date} {result.name}—"
                    f"its papers are another meeting's: {papers}"
                )
                continue
            results.append(result)
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        results: list[ScraperReturn] = []
        for year in sorted(wanted):
            url = _YEAR_URL.format(year=year)
            # A failed page is left to raise: production asks for one year,
            # so this is usually the only request, and swallowing it would
            # report a blocked or broken site as a council with no meetings.
            html = self.fetcher.fetch_with_requests(url)
            found = self._parse_page(html, url)
            if not found and year <= clock.current_year():
                # Future years are legitimately empty; a past or current one
                # is not.
                self.logger.warning(
                    f"{self.council_name}: no meetings with papers on {url}"
                )
            results.extend(found)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
