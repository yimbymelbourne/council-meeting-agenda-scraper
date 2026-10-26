import re
import urllib.parse

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.scrapers.nsw.dotted_time import colon_times

# The council's own meetings page. Before InfoCouncil it linked a page per
# meeting from here, and still does for 2023 ("21 December 2023 - Meeting
# documents"). Nothing earlier is linked anywhere on the site.
MEETINGS_PAGE = "https://www.gisc.nsw.gov.au/Council/Council-Meetings"

# The years before InfoCouncil's grid (2024 onwards) that the council site
# links meeting pages for; 2020–2022 are online nowhere. Asked for 2023 and
# finding no pages, the index has changed shape, not run out of meetings.
SITE_YEARS = {2023}

# /Council/Council-Meetings/2023-12-21-Meeting-documents; the capital D
# varies from page to page.
_MEETING_PAGE = re.compile(
    r"/Council/Council-Meetings/(\d{4})-(\d{2})-(\d{2})-Meeting-documents$",
    re.IGNORECASE,
)

# "Meeting Documents for the Ordinary Council Meeting to be held on ..."
_MEETING_TYPE = re.compile(r"for the (\w+) Council Meeting", re.IGNORECASE)


@register_scraper
class GlenInnesSevernScraper(InfoCouncilScraper):
    # InfoCouncil holds Council meetings only, from 2024. Asking for a year it
    # does not hold (2020–2023, 2027) returns the current year's grid instead.
    # Those rows are dated in the current year, so the base class's check that
    # each row's date is in the year asked for already drops them. 2023 comes
    # from the council site instead—see `_council_site_meetings`.
    tidy_meeting_rows = True

    # Glen Innes labels its supplementary rows "Council Late" and
    # "Extraordinary Council Late" (file `..._SUP.PDF`).
    SUPPLEMENTARY_NAME_REGEX = re.compile(
        r"\s*-?\s*\b(?:Supplementary|Late Items|Late)\b", re.IGNORECASE
    )

    def __init__(self):
        super().__init__(
            "glen_innes_severn",
            "NSW",
            "https://www.gisc.nsw.gov.au",
            "https://gleninnessevern.infocouncil.biz/",
        )

    def scraper(self) -> list[ScraperReturn]:
        # The grid sometimes writes the time with a dot and no am/pm
        # ("22 Oct 2026 9.00"), which the shared time parsing reads as
        # midnight; see dotted_time. The council-site meetings below carry
        # no time.
        results = colon_times(super().scraper())

        years_filter = getattr(self, "years_filter", None)
        wanted = (
            set(years_filter)
            if years_filter
            else set(range(EARLIEST_YEAR, clock.current_year() + 3))
        )
        # Only years the site has pages for are worth the index request;
        # production asks for the current year, so it never fetches these.
        older = wanted & SITE_YEARS
        if older:
            results += self._council_site_meetings(older)
        return results

    def _council_site_meetings(self, years: set[int]) -> list[ScraperReturn]:
        """The meetings the council site still links a page for, in `years`.

        Fetch errors propagate: a missing year here is a council that looks
        complete and is not.
        """
        index = BeautifulSoup(
            self.fetcher.fetch_with_requests(MEETINGS_PAGE), "html.parser"
        )
        pages = {}
        for link in index.find_all("a", href=True):
            url = urllib.parse.urljoin(MEETINGS_PAGE, link["href"].strip())
            match = _MEETING_PAGE.search(urllib.parse.urlparse(url).path)
            if match and int(match.group(1)) in years:
                pages[url] = "-".join(match.groups())
        if not pages:
            # Without this the 2023 meetings would vanish quietly if the
            # index stopped linking them.
            raise RuntimeError(
                f"{self.council_name}: {MEETINGS_PAGE} links no meeting pages "
                f"for {sorted(years)}"
            )

        results = []
        for url, date in pages.items():
            page = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
            content = page.find(id="main-content") or page
            agenda_url = minutes_url = None
            for link in content.find_all("a", href=True):
                href = link["href"].strip()
                if not urllib.parse.urlparse(href).path.lower().endswith(".pdf"):
                    continue
                label = link.get_text(" ", strip=True)
                # "Business Paper - 21.12.23 (PDF, 2MB)", "Minutes - 21.12.23
                # (PDF, 473KB)"; the third file, "Annexures", is the
                # attachments book and is neither.
                if re.match(r"^Business Paper\b", label, re.IGNORECASE):
                    agenda_url = agenda_url or urllib.parse.urljoin(url, href)
                elif re.match(r"^Minutes\b", label, re.IGNORECASE):
                    minutes_url = minutes_url or urllib.parse.urljoin(url, href)
            if not agenda_url and not minutes_url:
                continue

            kind = _MEETING_TYPE.search(content.get_text(" ", strip=True))
            # Named as InfoCouncil names them: "Council" and "Extraordinary
            # Council".
            name = (
                "Extraordinary Council"
                if kind and kind.group(1).lower() in ("extraordinary", "special")
                else "Council"
            )
            results.append(
                ScraperReturn(
                    name=name,
                    date=date,
                    time=None,
                    webpage_url=url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return results
