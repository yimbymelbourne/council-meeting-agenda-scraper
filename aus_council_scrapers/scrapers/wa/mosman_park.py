import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.mosmanpark.wa.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/council/agendas-minutes/"

# A WordPress archive of the theme's `key2_meetings` post type, ten meetings
# a page, newest first, each article carrying its documents inline under
# "Agenda", "Minutes", "Attachments" and "Notes" headings.
#
# The archive has a `?meetings-in=<year>` filter, but it leaves out meetings
# that have not happened yet—the upcoming Agenda Forum is on the unfiltered
# first page and on no year page. So this walks the unfiltered archive from
# the newest end and stops at the first page that ends before the earliest
# year wanted: three requests for the current year, about twenty-five for
# the full history. The REST route for the post type is not exposed.
_PAGE_URL = f"{_LISTING_URL}page/{{page}}/"
_MAX_PAGES = 60

# Minutes are occasionally filed under Attachments instead ("Download OCM
# Minutes_20220524"). Used only when the Minutes section is empty, and never
# for a link that is itself an attachment.
# Not \b: in "Minutes_20220524" the underscore is a word character, so there
# is no word boundary after "Minutes" and \bminutes\b never matched.
_MINUTES_LABEL = re.compile(r"(?<![a-z])minutes(?![a-z])", re.IGNORECASE)
_ATTACHMENT_LABEL = re.compile(r"attach|separate|late|report", re.IGNORECASE)


@register_scraper
class MosmanParkScraper(BaseScraper):
    def __init__(self):
        super().__init__("mosman_park", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _documents(article) -> tuple[str, str]:
        sections: dict[str, list] = {}
        for block in article.select(".doc-list"):
            heading = block.select_one(".doc-type")
            if heading:
                kind = heading.get_text(" ", strip=True).lower()
                # PDFs only: ScraperReturn promises PDF links, and the
                # pipeline reads them as PDFs. The one non-PDF in the 2020+
                # archive is the 15 February 2022 Electors' AGM minutes,
                # published only as Word, so that meeting carries its agenda
                # alone.
                sections.setdefault(kind, []).extend(
                    link
                    for link in block.select("a[href]")
                    if urlsplit(link["href"]).path.lower().endswith(".pdf")
                )

        agenda = next(iter(sections.get("agenda", [])), None)
        minutes = next(iter(sections.get("minutes", [])), None)
        if minutes is None:
            minutes = next(
                (
                    link
                    for link in sections.get("attachments", [])
                    if _MINUTES_LABEL.search(link.get_text(" ", strip=True))
                    and not _ATTACHMENT_LABEL.search(link.get_text(" ", strip=True))
                ),
                None,
            )
        return (
            urljoin(_BASE_URL, agenda["href"]) if agenda else None,
            urljoin(_BASE_URL, minutes["href"]) if minutes else None,
        )

    @staticmethod
    def _name(heading: str) -> str:
        # A few posts are titled after their document ("Agenda Forum Agenda",
        # "Swearing in Ceremony Agenda") rather than the meeting.
        name = re.sub(r"\s+agenda\s*$", "", heading, flags=re.IGNORECASE)
        return name.strip() or heading

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        earliest = min(wanted)

        results: dict[tuple, ScraperReturn] = {}
        errors: list[Exception] = []
        for page in range(1, _MAX_PAGES + 1):
            url = _LISTING_URL if page == 1 else _PAGE_URL.format(page=page)
            try:
                soup = BeautifulSoup(
                    self.fetcher.fetch_with_requests(url), "html.parser"
                )
            except Exception as e:
                self.logger.warning(f"Could not read {url}: {e}")
                errors.append(e)
                break

            articles = soup.select("article.meeting-item")
            dates = []
            for article in articles:
                heading = article.select_one(".entry-header h2")
                when = article.select_one(".entry-header .date")
                if not heading or not when:
                    continue
                date = parse_date(when.get_text(" ", strip=True), dayfirst=True).date()
                dates.append(date)
                if date.year not in wanted:
                    continue

                agenda_url, minutes_url = self._documents(article)
                if not agenda_url and not minutes_url:
                    continue

                name = self._name(
                    re.sub(r"\s+", " ", heading.get_text(" ", strip=True))
                )
                key = (name, date)
                existing = results.get(key)
                if existing:
                    # The same meeting posted twice (Audit Committee, 16
                    # February 2021, once with its minutes re-uploaded). Keep
                    # the newer post and only fill what it lacks.
                    existing.agenda_url = existing.agenda_url or agenda_url
                    existing.minutes_url = existing.minutes_url or minutes_url
                    existing.download_url = existing.agenda_url or existing.minutes_url
                    continue
                results[key] = ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )

            if not articles or not soup.select_one("a.next.page-numbers"):
                break
            # Newest first: once a page reaches back past the earliest year
            # wanted, every later page is older still.
            if dates and min(dates).year < earliest:
                break

        meetings = list(results.values())
        # Production asks for one year, so one failed fetch can leave
        # nothing. An empty list does not raise, and main.py would count the
        # council as working with 0 meetings. Raise instead; a failure that
        # still leaves other years' meetings stays a warning.
        if not meetings and errors:
            raise errors[-1]
        if not meetings:
            self.logger.warning(f"{self.council_name}: no meetings found")
        self.logger.info(f"{self.council_name} scraper found {len(meetings)} meetings")
        return meetings
