import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.geelongcity.vic.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/council-meetings"

# The "Past meetings" view on the council-meetings page is a Drupal view of
# every Council and Planning Committee meeting since 2012, 36 cards a page,
# newest first. Each card carries the meeting's PDFs inline, so the listing is
# all we read. A meeting is listed only once it has papers: on 20 October 2026
# the 27 October meeting was announced on the page but had no card yet.
#
# The view takes a date range (`field_date[min]`/`[max]`), which keeps one
# production year to a single listing page. But a handful of cards were
# re-uploaded without a date—"Council Meeting 24-03-2026", "Special Council
# Meeting 07-10-2025"—and a date filter never matches them. They sort after
# 2012 on the unfiltered view's last page, so that page is read as well. Some
# of them duplicate a dated card (24 March 2026) and one is the only card for
# its meeting (the 7 October 2025 special meeting).
_PAGE_SIZE = 36
_MAX_PAGES_PER_YEAR = 5

# The view's own markup; if it goes, the page has changed shape and an empty
# result would be a lie.
_VIEW_FORM_ID = "views-exposed-form-meeting-search-block-1"

# Links are labelled by hand and often just the filename
# ("council_meeing_agenda_-_25_november_2025.pdf"), so the label and the
# filename are read together, as substrings: "councilmeetingminutes" has no
# word boundary to match on. A mayoral minute is a document of its own;
# question-time responses and statements are neither paper.
_MINUTES = re.compile(r"minutes", re.IGNORECASE)
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
_NOT_A_PAPER = re.compile(
    r"mayoral|supplementary|addendum|attachment|late\s*item|question|statement",
    re.IGNORECASE,
)

# Undated cards write the date as DD-MM-YYYY.
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b")


def _link_labelled(tag, label: str):
    """The first link whose text (spans and all) is `label`."""
    for link in tag.find_all("a", href=True):
        if link.get_text(" ", strip=True).endswith(label):
            return link
    return None


# A name that says more than the default one, kept when two cards merge.
_SPECIFIC_NAME = re.compile(r"special|mayoral|statutory", re.IGNORECASE)


def _same_meeting(a: ScraperReturn, b: ScraperReturn) -> bool:
    """Whether two cards are one meeting listed twice.

    Two shapes occur. An undated re-upload ("Council Meeting 24-03-2026")
    repeats a dated card with copies of its files, so the files differ but
    the date and kind match; listing order puts the dated card first. And
    the 2022-24 archive lists most special meetings twice, once as
    "Ordinary" and once as "Special", both pointing at the one minutes file
    (12 October 2022, 10 April 2024: neither is an ordinary-meeting night).
    "Mayoral Election and Ordinary Council Meeting" sits beside "Ordinary
    Council Meeting" on 26 November 2024 the same way.
    """
    if a.date != b.date:
        return False
    if ("planning" in a.name.lower()) != ("planning" in b.name.lower()):
        return False
    shared = {a.agenda_url, a.minutes_url} & {b.agenda_url, b.minutes_url} - {None}
    if shared:
        return True
    return ("special" in a.name.lower()) == ("special" in b.name.lower())


def _fold(kept: ScraperReturn, other: ScraperReturn) -> None:
    kept.agenda_url = kept.agenda_url or other.agenda_url
    kept.minutes_url = kept.minutes_url or other.minutes_url
    kept.download_url = kept.agenda_url or kept.minutes_url
    if _SPECIFIC_NAME.search(other.name) and not _SPECIFIC_NAME.search(kept.name):
        kept.name = other.name
        kept.webpage_url = other.webpage_url


@register_scraper
class GreaterGeelongScraper(BaseScraper):
    def __init__(self):
        super().__init__("greater_geelong", "VIC", _BASE_URL)

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(set(years_filter))
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _rows(self, url: str) -> tuple:
        html = self.fetcher.fetch_with_requests(url)
        soup = BeautifulSoup(html, "html.parser")
        if not soup.find("form", id=_VIEW_FORM_ID):
            raise ValueError(f"No meeting view on {url}; the page has changed shape")
        return soup.select("div.views-row"), soup

    def _year_rows(self, year: int) -> list:
        rows = []
        for page in range(_MAX_PAGES_PER_YEAR):
            url = (
                f"{_LISTING_URL}?field_date%5Bmin%5D={year}-01-01"
                f"&field_date%5Bmax%5D={year}-12-31"
            )
            if page:
                url += f"&page={page}"
            page_rows, _ = self._rows(url)
            rows.extend(page_rows)
            if len(page_rows) < _PAGE_SIZE:
                break
        return rows

    def _undated_rows(self) -> list:
        """The cards with no date, from the end of the unfiltered view."""
        first_rows, soup = self._rows(_LISTING_URL)
        last = _link_labelled(soup, "Last page")
        if last is None:
            return first_rows
        match = re.search(r"page=(\d+)", last["href"])
        if not match or match.group(1) == "0":
            return first_rows
        last_rows, _ = self._rows(f"{_LISTING_URL}?page={match.group(1)}")
        return last_rows

    @staticmethod
    def _date(title: str, date_regex) -> tuple:
        match = date_regex.search(title)
        if match and not _NUMERIC_DATE.fullmatch(match.group()):
            return parse_date(match.group(), dayfirst=True).date(), match.group()
        numeric = _NUMERIC_DATE.search(title)
        if numeric:
            day, month, year = (int(g) for g in numeric.groups())
            return parse_date(f"{year}-{month:02d}-{day:02d}").date(), numeric.group()
        return None, None

    @staticmethod
    def _papers(row) -> tuple:
        agenda_url = None
        minutes_url = None
        for link in row.find_all("a", href=True):
            href = urljoin(_BASE_URL, link["href"])
            if "/sites/default/files/" not in href or not href.lower().endswith(
                ".pdf"
            ):
                continue
            label_tag = link.find("span")
            label = label_tag.get_text(" ", strip=True) if label_tag else ""
            text = f"{label} {href.rsplit('/', 1)[-1]}"
            # "Council Meeting Minutes - No Attachments" is the minutes.
            text = re.sub(r"no[\s_-]+attachments", "", text, flags=re.I)
            if _NOT_A_PAPER.search(text):
                continue
            if _MINUTES.search(text):
                minutes_url = minutes_url or href
            elif _AGENDA.search(text):
                agenda_url = agenda_url or href
        return agenda_url, minutes_url

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        rows = []
        for year in wanted:
            rows.extend(self._year_rows(year))
        rows.extend(self._undated_rows())

        results: list[ScraperReturn] = []
        for row in rows:
            heading = row.find("h3")
            if not heading:
                continue
            title = re.sub(r"\s+", " ", heading.get_text(" ", strip=True))
            date, date_text = self._date(title, self.date_regex)
            if date is None or date.year not in wanted:
                continue

            agenda_url, minutes_url = self._papers(row)
            if not agenda_url and not minutes_url:
                continue

            name = re.sub(r"\s+", " ", title.replace(date_text, " "))
            name = name.strip(" -–—") or "Council Meeting"
            name = re.sub(r"\s+-\s+\(", " (", name)

            more = _link_labelled(row, "View More")
            webpage_url = urljoin(_BASE_URL, more["href"]) if more else _LISTING_URL

            record = ScraperReturn(
                name=name,
                date=date.isoformat(),
                time=None,
                webpage_url=webpage_url,
                agenda_url=agenda_url,
                minutes_url=minutes_url,
                download_url=agenda_url or minutes_url,
            )
            twin = next((r for r in results if _same_meeting(r, record)), None)
            if twin is None:
                results.append(record)
            else:
                _fold(twin, record)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
