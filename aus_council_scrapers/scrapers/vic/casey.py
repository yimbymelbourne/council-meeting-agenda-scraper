import json
from urllib.parse import urljoin

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.casey.vic.gov.au"
_LISTING_URL = f"{_BASE_URL}/access-past-meetings-minutes-agendas"

# The listing page is an empty table that a Backbone collection fills from
# this JSON view (the `coc_council_meetings` Drupal module). Reading the view
# directly skips the HTML entirely: each row already carries the meeting
# type, its local date, and site-relative paths straight to the agenda and
# minutes PDFs. Filtered by year it is one request a year—10 to 25 rows,
# well inside the view's 50-row page—and that is what lets years_filter
# bound the production fetch to a single request.
#
# A scout probe once got a 406 from this view, but that was not reproduced
# in October 2026: it answered 200 with JSON to Accept text/html, */* and
# DefaultFetcher's own header set (which includes application/json anyway).
# If a 406 ever shows up, check the Accept header before anything else.
_API_URL = f"{_BASE_URL}/api/meetings?_format=json&year={{year}}"


@register_scraper
class CaseyScraper(BaseScraper):
    # The JSON view answers a GitHub-hosted runner with an empty body, which
    # json.loads cannot read, while a home connection gets the full JSON
    # (measured 20 Oct 2026 with the whole adapter run from a runner). The
    # front end is Varnish and sends no challenge header we recognise, so
    # rather than guess at a browser route, it goes through the residential
    # egress that already carries Cardinia and the two Baysides. See AGENTS.md,
    # "Councils that block GitHub's runners".
    egress = "residential"

    def __init__(self):
        super().__init__("casey", "VIC", _BASE_URL)

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(set(years_filter))
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _rows(self, year: int) -> list[dict]:
        rows: list[dict] = []
        page = 0
        while True:
            url = _API_URL.format(year=year)
            if page:
                url += f"&page={page}"
            data = json.loads(self.fetcher.fetch_with_requests(url))
            rows.extend(data.get("rows") or [])
            pager = data.get("pager") or {}
            total_pages = int(pager.get("total_pages") or 0)
            page += 1
            if page >= total_pages:
                return rows

    @staticmethod
    def _document(value) -> str | None:
        # Paths arrive with a trailing newline; an absent document is "" (and
        # on at least one malformed row, False).
        if not isinstance(value, str) or not value.strip():
            return None
        return urljoin(_BASE_URL, value.strip())

    def _meeting(self, row: dict) -> ScraperReturn | None:
        date = row.get("date")
        if not isinstance(date, str) or not date:
            # One row in the unfiltered view has date=False and no documents;
            # it is a broken node, not a meeting.
            return None
        if row.get("meeting_cancelled"):
            # Cancelled meetings keep their row, and sometimes the agenda
            # that was published before the cancellation. The meeting never
            # happened, so it is not one to alert anybody about.
            self.logger.debug(f"Skipping cancelled meeting on {date}")
            return None

        agenda_url = self._document(row.get("agenda"))
        minutes_url = self._document(row.get("minutes"))
        if not agenda_url and not minutes_url:
            return None

        return ScraperReturn(
            name=(row.get("type") or "").strip() or "Council Meeting",
            date=date,
            time=None,
            # Each row names a per-meeting page (/council-meetings/<slug>),
            # but those nodes are unpublished: every one tried answers 403,
            # to a browser User-Agent as well as ours. The listing page is
            # where a reader actually finds these documents.
            webpage_url=_LISTING_URL,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )

    @staticmethod
    def _documents(meeting: ScraperReturn) -> int:
        return bool(meeting.agenda_url) + bool(meeting.minutes_url)

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        # Casey's view can hold two nodes for one meeting: 27 May 2025's
        # Special Council Meeting appears twice, with the same agenda uploaded
        # under two file names and the minutes on only one of them. Keep the
        # fuller record for each meeting type and date.
        by_meeting: dict[tuple, ScraperReturn] = {}
        # One year's view failing is worth a warning and the rest of the run,
        # but production asks for a single year, so a failure there would
        # otherwise come back as an empty, "successful" scrape. When no year
        # could be read at all, the error is raised so the council reports
        # ok: false instead of zero meetings.
        last_error: Exception | None = None
        read_any = False
        for year in self._wanted_years():
            try:
                rows = self._rows(year)
            except Exception as e:
                self.logger.warning(f"Could not read Casey meetings for {year}: {e}")
                last_error = e
                continue
            read_any = True
            for row in rows:
                meeting = self._meeting(row)
                if not meeting:
                    continue
                key = (meeting.name, meeting.date)
                kept = by_meeting.get(key)
                if kept is None or self._documents(meeting) > self._documents(kept):
                    by_meeting[key] = meeting

        if not read_any and last_error is not None:
            raise last_error

        results = list(by_meeting.values())

        if not results:
            self.logger.warning("Casey's meetings view returned no meetings with documents")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
