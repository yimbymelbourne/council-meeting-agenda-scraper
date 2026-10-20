import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import isoparse

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.bendigo.vic.gov.au"
_MEETINGS_URL = f"{_BASE_URL}/about-us/council/council-meetings"
_SITEMAP_URL = f"{_BASE_URL}/sitemap.xml"

# Every Council meeting is an event page (/events/council-meeting-...), and
# its agenda, minutes, start time and title are only on that page. The event
# pages are found from the site's sitemap, which lists every one the council
# keeps online (from January 2022; it keeps four years), past and scheduled.
# The past-meetings view (/past-council-meetings) is not used: its pager is
# unstable, repeating a card at some page boundaries and skipping one at
# others, so it silently dropped the 23 April 2025 and 23 October 2023
# meetings (checked 20 Oct 2026). The council-meetings page is read as well,
# for any meeting posted since the sitemap was last built (Drupal caches it
# for up to three hours). Only Council meetings exist; the council has no
# planning committee.
#
# The slug carries the meeting's date ("council-meeting-monday-april-20-2026",
# "special-council-meeting-november-8-2022"), so only the wanted years' pages
# are fetched. One production year is the sitemap, the council-meetings page
# and about a dozen event pages.
_EVENT_SLUG = re.compile(r"/events/[a-z0-9-]*council-meeting-[a-z0-9-]*?-(\d{4})$")
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")

_AGENDA = re.compile(r"\bagenda\b", re.I)
_MINUTES = re.compile(r"\bminutes\b", re.I)
_NOT_A_PAPER = re.compile(r"assembl|attachment|supplementary|addendum", re.I)

# Titles repeat the date: "Council meeting Monday September 21, 2026".
_TITLE_DATE = re.compile(
    r"\s*(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day\s+)?"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}\s*$",
    re.I,
)


@register_scraper
class GreaterBendigoScraper(BaseScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 25 s (the
    # sitemap, the council-meetings page and 12 event pages). Orders
    # dispatch only.
    expected_seconds = 25

    def __init__(self):
        super().__init__("greater_bendigo", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _sitemap_events(self) -> dict[str, int]:
        """Event URL -> the year in its slug, for every Council meeting."""
        xml = self.fetcher.fetch_with_requests(_SITEMAP_URL)
        locs = _LOC.findall(xml)
        # Drupal's simple_sitemap splits a big site into an index of pages
        # (?page=N); this one is a single page of about 1,300 links today.
        if "<sitemapindex" in xml:
            locs = [
                loc
                for child in locs
                for loc in _LOC.findall(self.fetcher.fetch_with_requests(child))
            ]
        events = {}
        for loc in locs:
            match = _EVENT_SLUG.search(loc)
            if match:
                events[loc] = int(match.group(1))
        if not events:
            raise ValueError(f"No council-meeting events in {_SITEMAP_URL}")
        return events

    def _listed_events(self) -> dict[str, int]:
        """Event URL -> year, from the council-meetings page's cards."""
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_MEETINGS_URL), "html.parser"
        )
        events = {}
        for link in soup.find_all("a", href=True):
            if not link["href"].startswith("/events/"):
                continue
            stamp = link.find("time", attrs={"datetime": True})
            if stamp:
                url = urljoin(_BASE_URL, link["href"])
                events[url] = isoparse(stamp["datetime"]).year
        if not events:
            raise ValueError(f"No meeting cards on {_MEETINGS_URL}")
        return events

    def _meeting(self, url: str):
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        main = soup.find("main") or soup

        heading = soup.find("h1")
        stamp = main.find("time", attrs={"datetime": True})
        if not heading or not stamp:
            raise ValueError(f"No title or start time on {url}; the page has changed shape")
        start = isoparse(stamp["datetime"])
        title = re.sub(r"\s+", " ", heading.get_text(" ", strip=True))

        agenda_url = None
        minutes_url = None
        for link in main.find_all("a", href=True):
            href = urljoin(_BASE_URL, link["href"])
            # Most papers are Drupal files; a few large ones are on the
            # council's file host (public.bendigo.vic.gov.au/file/council/...,
            # the 16 September 2024 agenda). That host's robots.txt is
            # `Disallow: /`, so its URL is emitted as found and never fetched.
            is_pdf = href.lower().endswith(".pdf") or "pdf" in link.get(
                "data-file-type", ""
            )
            if not is_pdf:
                continue
            label = link.get_text(" ", strip=True)
            if _NOT_A_PAPER.search(label):
                continue
            if _MINUTES.search(label):
                minutes_url = minutes_url or href
            elif _AGENDA.search(label):
                agenda_url = agenda_url or href

        venue = main.select_one(".field--name-field-town")
        location = venue.get_text(" ", strip=True) if venue else None

        name = _TITLE_DATE.sub("", title).strip(" -") or "Council Meeting"
        # Titles are hand-typed: "Council meeting" and "Council Meeting".
        name = re.sub(r"\bmeeting\b", "Meeting", name)

        return start, ScraperReturn(
            name=name,
            date=start.date().isoformat(),
            time=start.strftime("%I:%M %p").lstrip("0"),
            webpage_url=url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
            location=location or None,
        )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        events = self._sitemap_events()
        for url, year in self._listed_events().items():
            events.setdefault(url, year)

        results: list[ScraperReturn] = []
        past = 0
        for url in sorted(u for u, year in events.items() if year in wanted):
            start, meeting = self._meeting(url)
            if start.year not in wanted:
                continue
            if start.date() < clock.today():
                past += 1
            # A meeting with neither paper is scheduled, not yet papered.
            if meeting.agenda_url or meeting.minutes_url:
                results.append(meeting)

        # Every past meeting has its papers posted, so past meetings with
        # none at all means the event page's links have changed shape, not
        # that the council stopped publishing.
        if past and not any(m.date < clock.today().isoformat() for m in results):
            raise ValueError(
                f"{past} past meetings in {sorted(wanted)} but no papers on any of them"
            )

        results.sort(key=lambda m: m.date)
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
