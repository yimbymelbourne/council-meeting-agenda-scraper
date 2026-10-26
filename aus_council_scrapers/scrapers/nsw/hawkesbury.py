"""Hawkesbury City Council—Squiz Matrix pages, one per year.

The current year's papers are on the Business Papers page. Every earlier
year has a page of its own under ``/_resources/.../past-business-papers/``,
linked from the Past Business Papers page; the slugs differ by era
(``business-papers-2025``, but plain ``2018`` for 2010–2018), so they are
read off that page rather than built.

Each year page is a set of month accordions (``h3.panel-title``) holding one
``h4`` per meeting, whose text is the meeting's date, followed by that
meeting's files. Most files are item attachments ("AT1toItem9.2.1 - ...",
"Attachment 2 to Item 8.1.1", "Appendix A to Attachment 1 ..."); the papers
are the agenda, a supplementary or late-supplementary agenda, and the
minutes.

**The date is the h4's, not the folder's.** Each meeting's files sit in a
folder named for a date (``/3-february-2026/``), and three times the folder
is wrong: the 9 July 2024 meeting's files are in ``/2-july-2024/``, 4
February 2025's in ``/2-february-2025/`` and 14 September 2021's in
``/21-september-2021/``. The 9 July 2024 minutes read "Date of meeting: 9
July 2024", so the heading is right. Some h4s carry a note after the date
("31 January 2023 - The Council meeting ... was adjourned ...", "17 May
2023 - Extraordinary - Members of the public can attend ..."); only the date
and the word "Extraordinary" are read from it.

**Cancelled meetings are left out.** "8 March 2022 - Cancellation of
Ordinary Council Meeting 8 March 2022" and "Cancelled - 1 July 2025" each
keep the agenda that was issued, but no meeting was held.

**Names.** Labels before 2025 are bare ("Agenda", "Minutes"); from late 2025
they name the meeting ("Agenda - Ordinary Meeting - 3 February 2026"). A
meeting is "Extraordinary Meeting" when its heading, folder or papers say
so, "Ordinary Meeting" when its papers say that, and "Council Meeting"
otherwise, rather than guessing ordinary for the unlabelled years.

**Cost.** Each year page is 500–730 KB, because every attachment is listed.
Production reads the current page alone: one request. A past year adds the
index (another 500 KB) and that year's page.

**Cloudflare.** The site is behind Cloudflare. Through ``DefaultFetcher``
every request passed from a home IP (20 Oct 2026, 16 requests); a bare
``requests`` session with its default headers drew ``cf-mitigated:
challenge`` on about half of the same pages. Not yet measured from a GitHub
runner.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.hawkesbury.nsw.gov.au"
_CURRENT_URL = f"{_BASE_URL}/your-council/council-meetings-and-agendas/business-papers"
_PAST_URL = (
    f"{_BASE_URL}/your-council/council-meetings-and-agendas/past-business-papers"
)

# The past-year links read "Business Papers 2025 Read more".
_PAST_LINK_TEXT = re.compile(r"^Business Papers (\d{4})\b")
# The current page's files sit under /business-papers-<year>/.
_CURRENT_YEAR = re.compile(r"/current/business-papers-(\d{4})/")

_DATE = re.compile(
    r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August"
    r"|September|October|November|December)\s+(\d{4})\b",
    re.IGNORECASE,
)
_CANCELLED = re.compile(r"\bcancel", re.IGNORECASE)
_EXTRAORDINARY = re.compile(r"extraordinary", re.IGNORECASE)
_ORDINARY = re.compile(r"\bordinary\b", re.IGNORECASE)

# The paper's word leads the label ("Agenda", "Agenda.pdf", "Agenda for
# Ordinary Meeting - 16 June 2026", "Extraordinary Agenda", "Minutes, 8
# September 2026"). Supplementary and late papers ("Agenda - Supplementary",
# "Late Supplementary Agenda 10 March 2026", "PUBLIC Supplementary Agenda")
# are second documents, never the agenda, and attachments never lead with
# either word.
_AGENDA = re.compile(r"^(?:extraordinary\s+)?agenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"^minutes\b", re.IGNORECASE)
_SECOND_PAPER = re.compile(r"supplementary|late\b", re.IGNORECASE)


@register_scraper
class HawkesburyScraper(BaseScraper):
    # Refused from GitHub-hosted runners (403, 405 or a connection timeout,
    # measured 20 Oct 2026 by running every state shard from a runner) and
    # reachable from a home connection, so it goes through the residential
    # egress. See AGENTS.md, "Councils that block GitHub's runners".
    egress = "residential"

    def __init__(self):
        super().__init__("hawkesbury", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return {int(year) for year in years_filter}
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _text(element) -> str:
        return re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()

    def _past_pages(self) -> dict[int, str]:
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(_PAST_URL), "html.parser")
        pages = {}
        for anchor in soup.find_all("a", href=True):
            match = _PAST_LINK_TEXT.match(self._text(anchor))
            if match and "/past-business-papers/" in anchor["href"]:
                pages[int(match.group(1))] = urljoin(_PAST_URL, anchor["href"])
        if not pages:
            raise RuntimeError(f"{self.council_name}: no year pages on {_PAST_URL}")
        return pages

    def _parse(self, html: str, page_url: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        # A page that loads but whose markup has changed would otherwise parse
        # to nothing and read as a year with no meetings. Every year page
        # reached here has files (the current page's year is read off them),
        # so no dated h4, or no file link, means the layout moved.
        if not soup.find("a", class_="related-document__link"):
            raise RuntimeError(
                f"{self.council_name}: no related-document__link files on {page_url}"
            )
        if not any(_DATE.search(self._text(h)) for h in soup.find_all("h4")):
            raise RuntimeError(
                f"{self.council_name}: no dated meeting headings on {page_url}"
            )
        results = []
        for heading in soup.find_all("h4"):
            heading_text = self._text(heading)
            match = _DATE.search(heading_text)
            if not match:
                # The footer's "Visit us", "Share and connect" and so on.
                continue
            if _CANCELLED.search(heading_text):
                continue
            date = parse_date(match.group(0)).date()

            agenda_url = minutes_url = None
            context = [heading_text]
            for element in heading.find_all_next(["h4", "a"]):
                if element.name == "h4":
                    break
                if "related-document__link" not in (element.get("class") or []):
                    continue
                href = element.get("href")
                if not href:
                    continue
                label = self._text(element)
                url = urljoin(page_url, href)
                if _SECOND_PAPER.search(label):
                    continue
                if agenda_url is None and _AGENDA.match(label):
                    agenda_url = url
                    context += [label, url]
                elif minutes_url is None and _MINUTES.match(label):
                    minutes_url = url
                    context += [label, url]

            if not agenda_url and not minutes_url:
                continue
            context_text = " ".join(context)
            if _EXTRAORDINARY.search(context_text):
                name = "Extraordinary Meeting"
            elif _ORDINARY.search(context_text):
                name = "Ordinary Meeting"
            else:
                name = "Council Meeting"
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=page_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        current_html = self.fetcher.fetch_with_requests(_CURRENT_URL)
        match = _CURRENT_YEAR.search(current_html)
        if not match:
            raise RuntimeError(
                f"{self.council_name}: cannot tell which year {_CURRENT_URL} holds"
            )
        current_year = int(match.group(1))

        results: list[ScraperReturn] = []
        if current_year in wanted:
            results.extend(self._parse(current_html, _CURRENT_URL))

        # The past index is fetched only when an earlier year is wanted, so
        # production's current-year run is the one request above. In January,
        # before the council starts the new year's page, the current page
        # still holds last year, and that is the year it serves.
        older = {year for year in wanted if year != current_year}
        if older:
            past = self._past_pages()
            for year in sorted((y for y in past if y in older), reverse=True):
                results.extend(
                    self._parse(
                        self.fetcher.fetch_with_requests(past[year]), past[year]
                    )
                )

        results = [r for r in results if int(r.date[:4]) in wanted]
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
