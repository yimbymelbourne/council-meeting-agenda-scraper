import datetime
import re
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.resolve import ResolveScraper

# The council-meetings page frames the Resolve portal, and below it lists
# the meetings from before the move, newest first, ten to a page
# (`?page=1`, `?page=2`, ...), each with its business paper and minutes on
# cdn.shellharbour.nsw.gov.au.
ARCHIVE_URL = "https://www.shellharbour.nsw.gov.au/council/council-meetings"

# robots.txt on www.shellharbour.nsw.gov.au.
CRAWL_DELAY = 10


@register_scraper
class ShellharbourScraper(ResolveScraper):
    # Shellharbour publishes through Resolve from its 1 February 2022
    # meeting. Everything before that is on the council-meetings page's
    # archive, read by `other_meetings`.
    tenant = "shellharbour"
    resolve_from = datetime.date(2022, 2, 1)

    # Council only: ordinary and extraordinary meetings (some extraordinary
    # meetings are typed Ordinary Council Meeting and named for what they
    # are). Left out are the Public Forum and "Councillor Questions and
    # Responses", which the council started listing in 2026. The ordinary
    # type was re-created in October 2024, and the old one renamed "Ordinary
    # Council Meeting - 2021 to Sept24", so both map to one name.
    meeting_types = re.compile(r"^(Ordinary|Extraordinary) Council Meeting\b")
    meeting_type_names = {
        "Ordinary Council Meeting - 2021 to Sept24": "Ordinary Council Meeting"
    }

    # "Councillor Questions and Responses - 24 February 2026" entered twice,
    # once under its own type (event 438) and once as an Ordinary Council
    # Meeting. Kept, it would be a second Ordinary Council Meeting that day,
    # with the councillors' questions as its agenda.
    skip_events = frozenset({433})

    def __init__(self):
        super().__init__("shellharbour", "NSW")

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        years = [y for y in self.before_resolve(wanted) if y >= EARLIEST_YEAR]
        if not years:
            # Production asks for the current year, so this costs nothing.
            return []
        oldest = min(years)

        results = []
        page = 0
        while True:
            if page:
                # Pages are fetched one after another, so the throttle alone
                # would not keep to the site's Crawl-delay.
                self.fetcher.sleep(CRAWL_DELAY)
            url = f"{ARCHIVE_URL}?page={page}" if page else ARCHIVE_URL
            rows = _archive_rows(self.fetcher.fetch_with_requests(url), url)
            if not rows:
                if page == 0:
                    raise RuntimeError(
                        f"{self.council_name}: no meetings in the archive at {url}"
                    )
                break
            for date, record in rows:
                if date.year not in years or date >= self.resolve_from:
                    continue
                if record:
                    results.append(record)
                else:
                    self.logger.warning(
                        f"{self.council_name}: archived meeting of {date} on "
                        f"{url} has no recognisable name or papers; skipped"
                    )
            # Newest first, so a page that ends before the oldest wanted year
            # is the last one needed.
            if rows[-1][0].year < oldest:
                break
            page += 1
        return sorted(results, key=lambda r: r.date)


# From May 2019 every archived meeting is titled "Ordinary Council Meeting
# <date>" or "Extraordinary Council Meeting <date>". Older ones are titled
# with the date or a file name, and some hold both meetings of a day in one
# row; none of those is in range.
_ARCHIVE_NAME = re.compile(r"\b((?:Extra)?ordinary Council Meeting)\b", re.IGNORECASE)

# The row's papers are "Business Paper" and "Minutes"; the other links are
# item attachments, mayoral minutes, late and declassified reports.
_BUSINESS_PAPER = re.compile(r"^business papers?$", re.IGNORECASE)
_MINUTES = re.compile(r"^minutes$", re.IGNORECASE)


def _archive_rows(
    html: str, url: str
) -> list[tuple[datetime.date, Optional[ScraperReturn]]]:
    """Each archived meeting's date, and its record where the row names one
    meeting and links its papers."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for article in soup.select("div.view-content article"):
        when = article.select_one("span.date-display-single[content]")
        if not when:
            continue
        # The meeting's local date and time, with its offset.
        date = datetime.datetime.fromisoformat(when["content"]).date()
        title = article.select_one("span[property='dc:title']")
        name = _ARCHIVE_NAME.search(title.get("content", "") if title else "")
        agenda_url = _paper(article, _BUSINESS_PAPER)
        minutes_url = _paper(article, _MINUTES)
        if not name or not (agenda_url or minutes_url):
            # Before 2019 a row is titled by its date alone and can hold an
            # ordinary and an extraordinary meeting's papers together. None
            # of those is in range; the date still says how far back the
            # page reaches.
            rows.append((date, None))
            continue
        rows.append(
            (
                date,
                ScraperReturn(
                    name=_title_case(name.group(1)),
                    date=date.isoformat(),
                    time=None,
                    webpage_url=url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                ),
            )
        )
    return rows


def _paper(article, label: re.Pattern) -> Optional[str]:
    for link in article.select("span.file a[href]"):
        if label.match(link.get_text(" ", strip=True)):
            return link["href"]
    return None


def _title_case(name: str) -> str:
    return " ".join(word.capitalize() for word in name.split())
