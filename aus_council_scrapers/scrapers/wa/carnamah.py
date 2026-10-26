import datetime
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.carnamah.wa.gov.au"
_LISTING_URL = f"{_BASE_URL}/your-shire/agendas-and-minutes/"

# A WordPress site whose meetings are a custom post type (key2_meetings),
# listed ten to a page as article.meeting-item cards: a title naming the
# meeting type, a full date, and doc-list blocks for the agenda, minutes and
# attachments. `?meetings-in=<year>` filters by meeting year server-side, so
# a production year is the year's first page plus one more.
#
# A documented robots.txt exception. www.carnamah.wa.gov.au/robots.txt has,
# under `User-Agent: *`:
#
#     Disallow: /wp-admin/
#     Disallow: /wp-content/plugins/
#     Disallow: /wp-content/uploads/
#     Disallow: /cgi-bin/
#
# (checked 26 Oct 2026; no Crawl-delay), and every agenda and minutes PDF is
# under /wp-content/uploads/. The scraper itself requests only the listing,
# which is allowed, but council-alerts downloads every document URL a
# scraper emits, so production does fetch the disallowed path. The
# maintainer decided on 26 Oct 2026 to accept that, as he did for swan,
# because these papers are the council's official public record. The
# exception covers the emitted papers only: the scraper still never fetches
# a document or any other disallowed path. See AGENTS.md before adding
# another.

# A file name carrying a full date ("Agenda-OCM-16-July-2025-Public.pdf",
# "20200617-Agenda-Ordinary-Council-Meeting.pdf").
_FILE_DATE_DMY = re.compile(
    r"(?<!\d)(\d{1,2})[-_ ]+([A-Za-z]{3,9})[-_ ]+(20\d\d)(?!\d)"
)
_FILE_DATE_YMD = re.compile(r"(?<!\d)(20\d\d)(\d\d)(\d\d)(?!\d)")

# How far a file's own date may sit from the card's before the link is taken
# to belong to another meeting. A day or two is a typo or the notice date
# ("Agenda-...-Electors-5-February-2025.pdf" on the 4 February card); the
# 15 July 2020 card's agenda link is "20200617-Agenda-...-Meeting2.pdf", the
# June meeting's agenda, and is dropped rather than emitted as July's.
_FILE_DATE_TOLERANCE_DAYS = 7

# A year's listing is empty until its first meeting is posted. A year with
# no meeting cards is an error only once this much of it has passed, the
# rule CraftMeetingsModuleScraper uses, so a markup change cannot pass for
# a council with no meetings.
_NEW_YEAR_GRACE_DAYS = 90


def _owed_papers(year: int) -> bool:
    """Whether a year has run long enough that it must have meetings."""
    today = clock.today()
    return year < today.year or (
        year == today.year
        and (today - datetime.date(year, 1, 1)).days >= _NEW_YEAR_GRACE_DAYS
    )


def _file_date(url: str):
    name = url.rsplit("/", 1)[-1]
    match = _FILE_DATE_YMD.search(name)
    if match:
        try:
            return datetime.date(*(int(g) for g in match.groups()))
        except ValueError:
            return None
    match = _FILE_DATE_DMY.search(name)
    if match:
        try:
            return parse_date(" ".join(match.groups())).date()
        except (ValueError, OverflowError):
            return None
    return None


@register_scraper
class CarnamahScraper(BaseScraper):
    def __init__(self):
        super().__init__("carnamah", "WA", _BASE_URL)

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(years_filter)
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _year(self, year: int) -> list[ScraperReturn]:
        results = []
        cards_seen = 0
        url = f"{_LISTING_URL}?meetings-in={year}"
        while url:
            soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
            cards = soup.select("article.meeting-item")
            cards_seen += len(cards)
            for card in cards:
                record = self._meeting(card, url)
                if record and record.cleaned_date.year == year:
                    results.append(record)
            following = soup.select_one("a.next[href]")
            url = urljoin(url, following["href"]) if following else None
        if not cards_seen and _owed_papers(year):
            raise ValueError(
                f"{self.council_name}: no meeting cards for {year} at "
                f"{_LISTING_URL}?meetings-in={year}"
            )
        return results

    def _meeting(self, card, page_url: str):
        title = card.select_one("h2.title")
        date_span = card.select_one("span.date")
        if not title or not date_span:
            return None
        date = parse_date(date_span.get_text(" ", strip=True)).date()

        papers = {}
        for kind in ("agenda", "minutes"):
            link = card.select_one(f"div.doc-list.{kind} a[href]")
            if not link:
                continue
            href = urljoin(page_url, link["href"])
            stated = _file_date(href)
            if stated and abs((stated - date).days) > _FILE_DATE_TOLERANCE_DAYS:
                self.logger.info(
                    f"{self.council_name}: {kind} for {date} links {href}, "
                    f"dated {stated}; left out"
                )
                continue
            papers[kind] = href

        if not papers:
            return None
        return ScraperReturn(
            name=re.sub(r"\s+", " ", title.get_text(" ", strip=True)),
            date=date.isoformat(),
            time=None,
            webpage_url=f"{_LISTING_URL}?meetings-in={date.year}",
            agenda_url=papers.get("agenda"),
            minutes_url=papers.get("minutes"),
            download_url=papers.get("agenda") or papers.get("minutes"),
        )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        results: list[ScraperReturn] = []
        errors: list[Exception] = []
        for year in self._wanted_years():
            try:
                results.extend(self._year(year))
            except Exception as e:
                self.logger.warning(f"{self.council_name}: could not read {year}: {e}")
                errors.append(e)

        # Production asks for one year, so a failed fetch there leaves
        # nothing; raise rather than report an ok council with 0 meetings.
        if errors and not results:
            raise errors[-1]
        if not results:
            self.logger.warning(
                f"{self.council_name}: no meetings with papers yet for "
                f"{self._wanted_years()}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
