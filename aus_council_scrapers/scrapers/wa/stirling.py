import datetime
import json
import urllib.parse

from aus_council_scrapers.alyka import (
    KsearchScraper,
    find_date,
    text_without_date,
    tidy_meeting_name,
)
from aus_council_scrapers.base import ScraperReturn, register_scraper

_BASE_URL = "https://www.stirling.wa.gov.au"
_LISTING_URL = (
    f"{_BASE_URL}/city-and-council/about-council/"
    "council-and-committee-meetings/minutes-and-agendas"
)

# Stirling's ksearch returns one record per meeting, already carrying the
# agenda and the minutes: `ArticleTitle` names the meeting and its date, and
# `Agenda` / `MinutesFile` are site-relative `/getmedia/` paths to the PDFs.
# Attachments and the YouTube recording ride along in other fields and are
# not the meeting's papers.
#
# The year filter is the site's own (`ArticleReleaseYear`) and is sent on
# every request, because the unfiltered listing is not the whole history: it
# returned 157 of the 273 meetings its `Total` claimed. Filtered by year, every
# year the page offers comes back whole or nearly so — 2026 yields 33 of a
# stated 36, the same 33 however it is paged or sorted.


@register_scraper
class StirlingScraper(KsearchScraper):
    listing_url = _LISTING_URL

    def __init__(self):
        super().__init__("stirling", "WA", _BASE_URL)

    @staticmethod
    def _offered_years(page) -> set[int]:
        """The years the page's own year filter offers (2021 onward today).

        Asking for one it does not offer is a wasted request: 2020 reports a
        Total of 37 and returns none of them.
        """
        element = page.find(attrs={"data-id": "ArticleReleaseYear"})
        try:
            return {int(o["Value"]) for o in json.loads(element["data-dataset"])}
        except Exception:
            return set()

    def _document(self, path: str) -> str:
        return urllib.parse.urljoin(_BASE_URL, path) if path else None

    def _from_record(self, record: dict) -> ScraperReturn:
        title = record.get("ArticleTitle") or ""
        if "cancelled" in title.lower():
            # Listed with a notice in the agenda slot; no meeting took place.
            return None

        # The title's date is the meeting's. `ArticleReleaseDate` usually
        # agrees, but not always: the 9 March 2021 Planning and Development
        # Committee was released on 5 March.
        found = find_date(title)
        if found:
            date = found[0]
        else:
            try:
                date = datetime.date.fromisoformat(
                    (record.get("ArticleReleaseDate") or "")[:10]
                )
            except ValueError:
                return None

        agenda_url = self._document(record.get("Agenda"))
        minutes_url = self._document(record.get("MinutesFile"))
        # The slots are filled by hand, and twice the minutes went into the
        # agenda slot as well; `_meeting` drops an agenda whose filename says
        # minutes. The display names are not consulted at all — the 1 August
        # 2023 Council Meeting has them swapped over correctly filed PDFs.
        if agenda_url and agenda_url == minutes_url:
            agenda_url = None

        return self._meeting(
            name=tidy_meeting_name(text_without_date(title)) or "Council Meeting",
            date=date,
            webpage_url=_LISTING_URL,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
        )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        page = self._listing_page()
        endpoint, search_param = self._ksearch_config(page)

        wanted = self._wanted_years()
        offered = self._offered_years(page)
        if offered:
            years = sorted(wanted & offered, reverse=True)
        else:
            self.logger.warning(
                f"{self.council_name}: could not read the year filter; "
                f"asking for every wanted year"
            )
            years = sorted(wanted, reverse=True)

        results = []

        def fetch(year):
            return self._ksearch(
                endpoint,
                search_param,
                [self.multiselect_filter("ArticleReleaseYear", [year])],
            )

        for _, records in self._each_year(years, fetch):
            for record in records:
                meeting = self._from_record(record)
                if meeting and meeting.cleaned_date.year in wanted:
                    results.append(meeting)

        self._log_result(results, f"years {sorted(years)}")
        return results
