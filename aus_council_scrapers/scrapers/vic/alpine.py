"""Alpine Shire Council (Bright, Myrtleford, Mount Beauty).

The council's Drupal 10 site keeps one page per year of meetings, linked from
an index. The index is read rather than the URLs built, because the pattern
changed: 2023 onwards is ``/council-meetings/council-meetings-YYYY`` and 2016–
2022 repeat the slug, ``/council-meetings-YYYY/council-meetings-YYYY``.

Two page templates, one per era, both holding each meeting's papers inline:

* 2025 onwards: a "related documents" paragraph per meeting, headed
  ``<h2>Ordinary Council Meeting - 27 January 2026</h2>``, with links labelled
  "M(1) 27 JANUARY 2026 - AGENDA (F)", "... - ATTACHMENTS (F)" and
  "... - MINUTES (F)". Meetings not yet held are listed with no documents.
* 2024 and earlier: an accordion item per meeting, titled
  "Ordinary Council Meeting - 30 January 2024", with links labelled just
  "Agenda", "Attachments" and "Minutes".

So the date and meeting type come from the heading, and which paper a link is
comes from its label. The attachment books are left out: they are the reports'
appendices, not the agenda.

A DocsPublished organisation ``alpineshire`` also exists, but holds only six
meetings from January to June 2025 and has not been updated since—this site is
the record.
"""

from __future__ import annotations

import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.ionata import text_date

_BASE_URL = "https://www.alpineshire.vic.gov.au"
_INDEX_URL = f"{_BASE_URL}/about-us/our-council/council-meetings"

# The year a page holds, from its index link ("Council Meetings 2026").
_YEAR_LINK = re.compile(r"^council meetings (20\d\d)$", re.IGNORECASE)

# One block per meeting, in either template.
_MEETING_BLOCKS = (
    "div.paragraph--type--pt8-related-documents, "
    "div.paragraph--type--pt11-1-accordion-item"
)
_MEETING_TITLE = "h2.paragraph__h2, .field--name-field-title"

# "Ordinary Council Meeting - 27 January 2026", "Joint Council Meeting -
# 13 August 2024".
_TITLE = re.compile(r"^(?P<name>.+?)\s+[-–—]\s+(?P<date>\d{1,2}\s+\w+\s+\d{4})$")

_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
# "Attachments", "Attachments Part A", "Attachment - Draft Land Development
# Strategy": appendices, never the paper itself.
_ATTACHMENT = re.compile(r"\battachments?\b", re.IGNORECASE)


def _filename_date(url: str) -> Optional[datetime.date]:
    """The date a document's filename spells out, if it spells one out.

    The filenames are percent-encoded ("M%288%29-%2029%20August%202023"), so
    they are decoded first; a filename with no year ("M2_3_March_Agenda.pdf")
    names no date.
    """
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1]).replace("_", " ")
    return text_date(name)


@register_scraper
class AlpineScraper(BaseScraper):
    def __init__(self):
        super().__init__("alpine", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return {int(year) for year in years_filter}
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _year_pages(self) -> dict[int, str]:
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(_INDEX_URL), "html.parser")
        pages: dict[int, str] = {}
        for link in soup.find_all("a", href=True):
            # The index cards read "Council Meetings 2026 Read more".
            label = re.sub(r"\s+read more$", "", link.get_text(" ", strip=True), flags=re.I)
            if match := _YEAR_LINK.match(label):
                pages.setdefault(int(match.group(1)), urljoin(_INDEX_URL, link["href"]))
        if not pages:
            raise RuntimeError(f"alpine: no year pages linked from {_INDEX_URL}")
        return pages

    def _papers(self, block: Tag) -> tuple[Optional[str], Optional[str]]:
        agenda_url = minutes_url = None
        for link in block.find_all("a", href=True):
            # The new template appends the file size in a span ("296.92 KB").
            size = link.find("span", class_="file-size")
            if size:
                size.extract()
            label = " ".join(link.get_text(" ", strip=True).split())
            url = urljoin(_BASE_URL, link["href"].strip())
            if not urlparse(url).path.lower().endswith(".pdf"):
                # The meeting recording on YouTube, an Eventbrite booking.
                continue
            if _ATTACHMENT.search(label):
                continue
            if _MINUTES.search(label):
                minutes_url = minutes_url or url
            elif _AGENDA.search(label):
                agenda_url = agenda_url or url
        return agenda_url, minutes_url

    def _read_year(self, year: int, url: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        blocks = soup.select(_MEETING_BLOCKS)
        if not blocks:
            # Every year page since 2016 has its meetings in one template or
            # the other, so none at all is the site changing, not a quiet year.
            raise RuntimeError(f"alpine: no meeting blocks on {url}")
        meetings: list[tuple[ScraperReturn, dict[str, datetime.date]]] = []
        for block in blocks:
            title_el = block.select_one(_MEETING_TITLE)
            if title_el is None:
                # A related-documents paragraph without a heading is not a
                # meeting's (the 2026 page has none, but nothing forbids it).
                continue
            title = " ".join(title_el.get_text(" ", strip=True).split())
            match = _TITLE.match(title)
            if not match:
                self.logger.warning(f"alpine: unrecognised meeting heading {title!r} on {url}")
                continue
            date = parse_date(match.group("date"), dayfirst=True).date()
            if date.year != year:
                self.logger.warning(f"alpine: {title!r} is on the {year} page")
            agenda_url, minutes_url = self._papers(block)
            if not agenda_url and not minutes_url:
                # Scheduled but not yet held, with nothing published.
                continue
            named = {
                kind: found
                for kind, doc in (("agenda", agenda_url), ("minutes", minutes_url))
                if doc and (found := _filename_date(doc)) and found != date
            }
            meetings.append(
                (
                    ScraperReturn(
                        name=match.group("name"),
                        date=date.isoformat(),
                        time=None,
                        webpage_url=url,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    ),
                    named,
                )
            )
        return self._drop_misfiled(meetings)

    def _drop_misfiled(self, meetings: list[tuple]) -> list[ScraperReturn]:
        """Take a paper off a meeting when its filename is another meeting's.

        The pages are edited by hand, and a link copied from one meeting to
        the next is sometimes not repointed: the 28 February 2023 meeting's
        "Agenda" is ``M(8)- 29 August 2023 - Agenda (F).pdf``, the agenda the
        29 August meeting also links. A filename naming some other date is
        not enough on its own—the September 2025 minutes are filed as
        "M(10)" but dated right—so a paper is dropped only when its filename
        names a date that is another meeting on the same page.
        """
        dates = {record.date for record, _ in meetings}
        kept = []
        for record, named in meetings:
            for kind, found in named.items():
                if found.isoformat() in dates:
                    self.logger.warning(
                        f"alpine: the {kind} linked from the {record.date} meeting "
                        f"is the {found} meeting's; left out"
                    )
                    setattr(record, f"{kind}_url", None)
            if not record.agenda_url and not record.minutes_url:
                continue
            record.download_url = record.agenda_url or record.minutes_url
            kept.append(record)
        return kept

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        pages = self._year_pages()
        wanted = self._wanted_years()
        missing = sorted(y for y in wanted if y <= clock.current_year() and y not in pages)
        if missing:
            # A past or current year the index does not link. Early January
            # can be like this before the new year's page is added; later in
            # the year it means the index moved.
            self.logger.warning(f"alpine: no year page linked for {missing}")
        results: list[ScraperReturn] = []
        for year in sorted(pages, reverse=True):
            if year not in wanted or year < EARLIEST_YEAR:
                continue
            results.extend(self._read_year(year, pages[year]))
        if not results:
            self.logger.warning(f"alpine: no meetings with papers for {sorted(wanted)}")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
