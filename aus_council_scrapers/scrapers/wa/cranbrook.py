import datetime
import re
from typing import Optional

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_LISTING_URL = (
    "https://www.cranbrook.wa.gov.au/the-shire/your-council/council-meetings/"
)

# The listing is a WordPress archive of a `key2_meetings` post type, ten
# meetings a page, newest first. Its "Filter by Year" control is a plain
# `?meetings-in=<year>` query, so a production year is one or two requests
# rather than a walk back through all 17 unfiltered pages. Every body is in
# the one archive (Ordinary, Special, Audit, Electors), and at about 20
# meetings a year there is no need to cut it down by type.
#
# Each meeting's documents are grouped by kind in `div.doc-list.agenda`,
# `.minutes` and `.attachments`. The links themselves all read "Download
# Agenda"/"Download Minutes", so the group is what says which is which, and
# the attachments group (report attachments, financial statements) is never
# read.
_YEAR_URL = _LISTING_URL + "?meetings-in={year}"

# "Electors Meeting 2025": the year is already in the date.
_TRAILING_YEAR = re.compile(r"\s+\d{4}$")

# WordPress files an upload under /wp-content/uploads/<year>/<month>/, and
# Cranbrook names most papers with the meeting date (20260318-MINUTES.pdf).
_UPLOAD_FOLDER = re.compile(r"/wp-content/uploads/(\d{4})/(\d{2})/")
_FILENAME_DATE = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")


def _points_at_a_later_meeting(url: str, meeting_date: datetime.date) -> bool:
    """True when a link plainly carries another, later meeting's paper.

    The 19 March 2025 meeting's minutes link is the 18 March 2026 minutes,
    uploaded in April 2026—the same file the 2026 meeting links. A filename
    date alone is not enough to say so: the 18 February 2026 papers are named
    AGENDA-20250218.pdf and are the right papers with a typo in the name. What
    gives the March one away is that the file was also *uploaded* a year after
    the meeting, in agreement with its filename. Both have to hold.
    """
    folder = _UPLOAD_FOLDER.search(url)
    named = _FILENAME_DATE.search(url.rsplit("/", 1)[-1])
    if not folder or not named:
        return False
    try:
        file_date = datetime.date(*(int(g) for g in named.groups()))
    except ValueError:
        return False
    uploaded = datetime.date(int(folder.group(1)), int(folder.group(2)), 1)
    return (
        file_date != meeting_date
        and (uploaded - meeting_date).days > 180
        and abs((uploaded - file_date).days) < 90
    )


@register_scraper
class CranbrookScraper(BaseScraper):
    def __init__(self):
        super().__init__("cranbrook", "WA", "https://www.cranbrook.wa.gov.au")

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(set(years_filter))
        # Oldest first, so the year dropdown has been read before the two
        # years ahead come up, and they are skipped when nothing is scheduled.
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        results: list[ScraperReturn] = []
        offered: Optional[set[int]] = None

        for year in self._wanted_years():
            # The year dropdown lists only years that hold meetings, so once
            # one page has been read, a future year nobody has scheduled yet
            # costs nothing.
            if offered is not None and year not in offered:
                continue
            url: Optional[str] = _YEAR_URL.format(year=year)
            while url:
                soup = BeautifulSoup(
                    self.fetcher.fetch_with_requests(url), "html.parser"
                )
                if offered is None:
                    offered = self._offered_years(soup)
                results.extend(self._parse_page(soup, url))
                next_link = soup.select_one("a.next.page-numbers[href]")
                url = next_link["href"] if next_link else None

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    @staticmethod
    def _offered_years(soup) -> Optional[set[int]]:
        options = soup.select("#meetings-filter option[value]")
        years = {int(o["value"]) for o in options if o["value"].isdigit()}
        return years or None

    def _parse_page(self, soup, page_url: str) -> list[ScraperReturn]:
        meetings = []
        # `article.key2_meetings` is the archive. The "upcoming meetings" strip
        # above it on the first page repeats the next three as `li` items.
        for item in soup.select("article.meeting-item.key2_meetings"):
            title = item.select_one(".title")
            date_el = item.select_one(".date")
            if not title or not date_el:
                continue
            date_text = date_el.get_text(" ", strip=True)
            meeting_date = parse_date(date_text, dayfirst=True).date()

            papers = {}
            for kind in ("agenda", "minutes"):
                link = item.select_one(f"div.doc-list.{kind} a[href]")
                if not link:
                    continue
                href = link["href"]
                if _points_at_a_later_meeting(href, meeting_date):
                    self.logger.warning(
                        f"{self.council_name}: {date_text} {kind} links {href}, "
                        f"a later meeting's paper; leaving it off"
                    )
                    continue
                papers[kind] = href

            if not papers:
                # Scheduled meetings are listed before any paper is up.
                continue

            agenda_url = papers.get("agenda")
            minutes_url = papers.get("minutes")
            meetings.append(
                ScraperReturn(
                    name=_TRAILING_YEAR.sub("", title.get_text(" ", strip=True)),
                    date=meeting_date.isoformat(),
                    time=None,
                    webpage_url=page_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return meetings
