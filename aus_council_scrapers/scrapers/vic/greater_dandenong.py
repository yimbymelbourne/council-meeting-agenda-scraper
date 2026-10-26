import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.greaterdandenong.vic.gov.au"
_LISTING_URL = f"{_BASE_URL}/council-meetings"

# A Drupal view in two blocks. "Upcoming Meetings" is a fixed handful of the
# next meetings; "Past Meetings" is newest first, eight to a page, behind a
# "Load more" link that is a plain GET with ?page=N. The exposed date-range
# filter narrows the past block to one year, which is what lets years_filter
# bound the fetch, but it does not touch the upcoming block—that is
# repeated, unfiltered, on every page, so its meetings are de-duplicated and
# filtered by their own dates.
#
# The listing carries only titles ("Council Meeting - 21 September 2026");
# the agenda and minutes are on a page per meeting, so the cost is one request
# per meeting in range. Every meeting Greater Dandenong lists is a meeting of
# Council—there are no committee rows to leave out—so nothing is
# filtered by type. Production's one year is about 2 listing pages plus the
# ~13 meeting pages that year holds.
_CANCELLED = re.compile(r"\bcancelled\b", re.IGNORECASE)

# Documents are served from a file repository by record number
# (/_flysystem/filerepo?file=A14160859, or /_flysystem/filerepo/A7133017 on
# older pages) with no extension, so the link label is all that says what a
# file is: "Council Meeting Agenda 21 September 2026 - 177.9 MB", "Meeting
# Minutes - 7.42MB". "Agenda Item Timings" is a running sheet, not the agenda.
_DOCUMENT_HREF = re.compile(r"/_flysystem/filerepo")
_AGENDA_LABEL = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"\bminutes\b", re.IGNORECASE)
_NOT_THE_AGENDA = re.compile(r"item timings|supplementary|attachment", re.IGNORECASE)


@register_scraper
class GreaterDandenongScraper(BaseScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 27 s
    # (15 requests—2 listing pages and a page per meeting). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 27

    def __init__(self):
        super().__init__("greater_dandenong", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _year_of(self, title: str):
        match = self.date_regex.search(title)
        if not match:
            return None
        try:
            return parse_date(match.group(), dayfirst=True).year
        except (ValueError, OverflowError):
            return None

    def _listing(self, year: int) -> list[tuple[str, str]]:
        """(title, url) for every meeting on the year's pages, upcoming included."""
        params = {
            "field_date_range_value[min]": f"{year}-01-01",
            "field_date_range_value[max]": f"{year}-12-31",
        }
        url = f"{_LISTING_URL}?{urlencode(params)}"
        found: list[tuple[str, str]] = []
        seen_pages: set[str] = set()
        while url and url not in seen_pages:
            seen_pages.add(url)
            soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
            for title in soup.select("div.views-row div.title a[href]"):
                text = re.sub(r"\s+", " ", title.get_text(" ", strip=True))
                found.append((text, urljoin(_LISTING_URL, title["href"])))
            more = soup.select_one("nav.pager a[href], ul.pager a[href]")
            url = urljoin(_LISTING_URL, more["href"]) if more else None
        return found

    def _meeting(self, title: str, url: str) -> ScraperReturn | None:
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

        agenda_url = None
        minutes_url = None
        for link in soup.find_all("a", href=_DOCUMENT_HREF):
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            href = urljoin(url, link["href"])
            if minutes_url is None and _MINUTES_LABEL.search(label):
                minutes_url = href
            elif (
                agenda_url is None
                and _AGENDA_LABEL.search(label)
                and not _NOT_THE_AGENDA.search(label)
            ):
                agenda_url = href
        if not agenda_url and not minutes_url:
            # Scheduled but not yet papered.
            return None

        # The page states the start in a <time datetime>. Its "Z" is a lie—
        # 7 pm meetings are stamped T19:00:00Z—so the wall-clock digits are
        # read as local time rather than converted from UTC.
        stamp = soup.find("time", attrs={"datetime": True})
        if stamp:
            when = parse_date(stamp["datetime"].rstrip("Zz"))
            date = when.date().isoformat()
            time = when.strftime("%I:%M %p").lstrip("0")
        else:
            date = self.date_regex.search(title).group()
            time = None

        # The titles are mostly "Council Meeting - <date>", but the statutory
        # November meetings get event names instead: "Mayoral Election", "New
        # Council Sworn In", "Council Meeting - (Annual Meeting to Elect Mayor
        # and Deputy Mayor)". All are meetings of Council, so the type is the
        # words up to "Meeting" when the title has them, and Council Meeting
        # otherwise. A special meeting can be titled as an ordinary one and
        # say so only in its body ("This is a special Council Meeting").
        heading = soup.find("h1")
        title_text = heading.get_text(" ", strip=True) if heading else title
        body = soup.find("main") or soup
        typed = re.search(r"[A-Za-z ]*?\bmeeting\b", title_text, re.IGNORECASE)
        name = re.sub(r"\s+", " ", typed.group()).strip() if typed else "Council Meeting"
        if "special" not in name.lower() and re.search(
            r"\bspecial council meeting\b", body.get_text(" "), re.IGNORECASE
        ):
            name = "Special Council Meeting"

        return ScraperReturn(
            name=name,
            date=date,
            time=time,
            webpage_url=url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        this_year = clock.current_year()

        # Future years have no past block to page through; their meetings
        # can only appear in the upcoming block, which the current year's
        # listing carries.
        listing_years = sorted({min(y, this_year) for y in wanted}, reverse=True)

        # A failed listing or meeting page is a warning and the run goes on,
        # but production asks for a single year: if nothing at all could be
        # read, the last error is raised so the council reports ok: false
        # rather than an empty, "successful" scrape.
        last_error: Exception | None = None
        listings_read = 0
        candidates: dict[str, str] = {}
        for year in listing_years:
            try:
                listing = self._listing(year)
            except Exception as e:
                self.logger.warning(
                    f"Could not read Greater Dandenong's {year} listing: {e}"
                )
                last_error = e
                continue
            listings_read += 1
            for title, url in listing:
                if _CANCELLED.search(title):
                    # "MEETING CANCELLED - Council Meeting - 29 June 2026": the
                    # page survives but holds no documents.
                    continue
                year_of = self._year_of(title)
                if year_of is None:
                    # Every meeting title carries its date, the statutory
                    # November ones included ("Mayoral Election - 18 November
                    # 2024"). The undated rows are standing pages filed in the
                    # same view—"Council Meetings - Public Question Time",
                    # "Councillor Briefing Sessions"—with no documents, and
                    # fetching them would cost two requests a night.
                    continue
                if year_of not in wanted:
                    continue
                candidates.setdefault(url, title)
        if not listings_read and last_error is not None:
            raise last_error

        results: list[ScraperReturn] = []
        pages_read = 0
        for url, title in candidates.items():
            try:
                meeting = self._meeting(title, url)
            except Exception as e:
                self.logger.warning(f"Could not read {url}: {e}")
                last_error = e
                continue
            pages_read += 1
            if meeting and meeting.cleaned_date.year in wanted:
                results.append(meeting)
        if candidates and not pages_read and last_error is not None:
            raise last_error

        if not results:
            self.logger.warning(
                "Greater Dandenong's listing yielded no meetings with documents"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
