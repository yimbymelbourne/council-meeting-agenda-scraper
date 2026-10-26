import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.kalamunda.wa.gov.au"
_LISTING_URL = (
    "https://www.kalamunda.wa.gov.au/council/council-committees/agenda-minutes"
)

# Kalamunda (Sitefinity) lists every meeting since 2010 as a search result
# over its "meeting-minutes" index, newest first, 20 to a page. Each result
# is a `div.meeting-item` carrying the date and time, the meeting type, the
# venue, and the Agenda and Minutes links straight to the PDFs. The
# attachments sit apart under "Associated Documents" and are never read.
#
# The page is a path segment, not a query parameter, and the query string is
# not optional: without `indexCatalogue` the listing ignores the page number
# and serves page 1. With the catalogue named, `Year=` filters to one year—
# about 30 meetings, so two pages—which is what keeps a one-year production
# run to two requests instead of paging back through the whole history.
#
# Verified 2026-10-19 that the year-filtered pages hold exactly the meetings
# the unfiltered listing shows for that year (2025: 29 and 29). The newest
# result that day was the 13 October briefing forum: the listing showed
# nothing dated after today, and `Year=2027` came back empty. Later years are
# still asked for, at one request each, so upcoming meetings are picked up if
# the council starts listing them.
_PAGE_URL = (
    _LISTING_URL
    + "/{page}?indexCatalogue=meeting-minutes&searchQuery=&orderBy=Date&Year={year}"
)

_AGENDA_LABEL = re.compile(r"^\s*agenda\s*$", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"^\s*minutes\s*$", re.IGNORECASE)

# "13 October 2026 6:30 PM", and occasionally "01 September 2026 5:0 PM".
_WHEN = re.compile(
    r"(?P<date>\d{1,2}\s+[A-Za-z]+\s+\d{4})\s*"
    r"(?:(?P<hour>\d{1,2}):(?P<minute>\d{1,2})\s*(?P<ampm>[AP]M))?",
    re.IGNORECASE,
)

# Minor meeting types are filed as "Other - <type>", and two of them carry a
# document title rather than a type: "Other - Audit & Risk Committee Agenda -
# 21 July 2020".
_OTHER_PREFIX = re.compile(r"^\s*other\s*-\s*", re.IGNORECASE)
_TITLE_SUFFIX = re.compile(
    r"\s+agenda\s*-\s*\d{1,2}\s+[A-Za-z]+\s+\d{4}\s*$", re.IGNORECASE
)
# Two 2020 entries are filed as "Other - Draft Agenda - Ordinary Council
# Meeting". They fall on briefing-forum Tuesdays, two weeks before the
# Ordinary Council Meeting, and the draft agenda is what a briefing forum
# considers, so they are named as the forum they were.
_DRAFT_AGENDA = re.compile(r"^draft agenda\b", re.IGNORECASE)
_BRIEFING_FORUM = "Public Agenda Briefing Forum"

# A briefing forum decides nothing, so it has no minutes. Two 2020 forums
# link a "Minutes" document anyway, and it is the forum's notes ("Public
# Agenda Briefing Forum – 10 March 2020 NOTES"), so it is not stored as
# minutes. Perth and South Perth leave briefing notes out the same way.
_BRIEFING = re.compile(r"\bbriefing\b", re.IGNORECASE)

# "...-9-august-2022.pdf": a document's filename usually spells the date of
# the meeting it belongs to.
_FILE_DATE = "{day}-{month}-{year}"

# The venue is sometimes followed by a livestream link or a note:
# "Council Chambers, ... WA 6076 | YouTube: https://youtu.be/...".
_VENUE_TRAILER = re.compile(r"\s*(?:\|.*|\.?\s*NOTE:.*)$", re.IGNORECASE)

# A year holds about 30 meetings, so two pages. This only stops a pager that
# never ends.
_MAX_PAGES = 6


@register_scraper
class KalamundaScraper(BaseScraper):
    def __init__(self):
        council = "kalamunda"
        state = "WA"
        base_url = _BASE_URL
        super().__init__(council, state, base_url)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _name(text: str) -> str:
        name = re.sub(r"\s+", " ", text).strip()
        name = _OTHER_PREFIX.sub("", name)
        if _DRAFT_AGENDA.match(name):
            return _BRIEFING_FORUM
        return _TITLE_SUFFIX.sub("", name).strip()

    @staticmethod
    def _location(item) -> Optional[str]:
        for paragraph in item.select("p.meeting-item__content"):
            text = re.sub(r"\s+", " ", paragraph.get_text(" ", strip=True))
            if text.lower().startswith("venue:"):
                venue = _VENUE_TRAILER.sub("", text[len("venue:") :]).strip()
                return venue or None
        return None

    def _meeting(self, item, year: int, page_url: str) -> Optional[ScraperReturn]:
        when = item.select_one(".meeting-item__time")
        match = _WHEN.search(when.get_text(" ", strip=True)) if when else None
        if not match:
            return None
        date = parse_date(match.group("date"), dayfirst=True).date()
        if date.year != year:
            return None
        time = None
        if match.group("hour"):
            time = (
                f"{int(match.group('hour'))}:{int(match.group('minute')):02d} "
                f"{match.group('ampm').upper()}"
            )

        agenda_url = minutes_url = None
        for link in item.select("ul.card-links a[href]"):
            label = link.get_text(" ", strip=True)
            href = urljoin(page_url, link["href"])
            if _AGENDA_LABEL.match(label) and agenda_url is None:
                agenda_url = href
            elif _MINUTES_LABEL.match(label) and minutes_url is None:
                minutes_url = href
        name = item.select_one("p.meeting-item__content")
        name = self._name(name.get_text(" ", strip=True)) if name else "Council Meeting"
        if _BRIEFING.search(name):
            minutes_url = None
        if not agenda_url and not minutes_url:
            return None

        return ScraperReturn(
            name=name,
            date=date.isoformat(),
            time=time,
            webpage_url=page_url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
            location=self._location(item),
        )

    def _year(self, year: int):
        """Yield a year's meetings page by page.

        A generator, so a page that fails to load costs only the pages after
        it: the meetings already read from earlier pages have been handed
        over by then.
        """
        for page in range(1, _MAX_PAGES + 1):
            url = _PAGE_URL.format(page=page, year=year)
            soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
            for item in soup.select("div.meeting-item"):
                meeting = self._meeting(item, year, url)
                if meeting:
                    yield meeting

            more = any(
                f"/agenda-minutes/{page + 1}?" in link["href"]
                for link in soup.select("ul.pagination a[href]")
            )
            if not more:
                break

    @staticmethod
    def _drop_misfiled_agendas(results: list[ScraperReturn]) -> list[ScraperReturn]:
        """Take an agenda off a meeting it was linked to by mistake.

        The council sometimes links one meeting's agenda from another: the
        16 August 2022 Special Submissions Meeting links the 9 August 2022
        briefing forum's agenda, and has nothing of its own. When the same
        agenda is on more than one meeting and its filename spells one of
        their dates, it stays only on the meetings with that date; a meeting
        left with no documents is dropped. Shared agendas whose filenames
        name none of the dates are left as published.
        """
        by_url: dict[str, list[ScraperReturn]] = {}
        for meeting in results:
            if meeting.agenda_url:
                by_url.setdefault(meeting.agenda_url, []).append(meeting)

        for url, meetings in by_url.items():
            if len(meetings) < 2:
                continue
            filename = url.lower().split("?")[0].rsplit("/", 1)[-1]

            def spelled(meeting: ScraperReturn) -> bool:
                date = parse_date(meeting.date).date()
                return (
                    _FILE_DATE.format(
                        day=date.day, month=date.strftime("%B").lower(), year=date.year
                    )
                    in filename
                )

            if any(spelled(m) for m in meetings):
                for meeting in meetings:
                    if not spelled(meeting):
                        meeting.agenda_url = None
                        meeting.download_url = meeting.minutes_url

        return [m for m in results if m.agenda_url or m.minutes_url]

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        results: list[ScraperReturn] = []
        # A year that cannot be fetched is logged and skipped. But if nothing
        # at all comes back and a fetch failed, the failure is raised:
        # returning [] would report a blocked or down site as a council with
        # no meetings.
        last_error: Optional[Exception] = None
        for year in sorted(self._wanted_years(), reverse=True):
            try:
                for meeting in self._year(year):
                    results.append(meeting)
            except Exception as e:
                last_error = e
                self.logger.warning(f"Could not read the {year} meetings: {e}")

        results = self._drop_misfiled_agendas(results)
        if not results and last_error is not None:
            raise last_error
        if not results:
            self.logger.warning(f"{self.council_name} scraper found no meetings")
        else:
            self.logger.info(
                f"{self.council_name} scraper found {len(results)} meetings"
            )
        return results
