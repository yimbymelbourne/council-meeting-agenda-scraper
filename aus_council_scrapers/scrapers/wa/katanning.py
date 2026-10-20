from urllib.parse import urljoin

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_tidy import (
    WATidyCouncilConnectScraper,
)


@register_scraper
class KatanningScraper(WATidyCouncilConnectScraper):
    """Shire of Katanning—documents on each meeting's own page.

    Council meetings only. The other types are the Audit & Risk Committee
    and the electors' meeting, four or five a year, and each meeting costs a
    request to read its documents.

    Only Ordinary Council Meetings has per-type year pages. The special
    meetings' /council-meetings/special-council-meeting/past/<year> answers
    404 for every year, as does the type's own page (checked 20 Oct 2026),
    so each year is read from the all-types listing—two or three pages—and a
    meeting of any other type is skipped before its page is fetched. This is
    the same shape as Mundaring's CouncilConnect library.

    Headings are month-only ("Special Council Meeting - October 2025", and
    there were two that month); the date comes from the meeting page's date
    field, which is always a full date.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 31 s for
    # 15 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 31

    def __init__(self):
        super().__init__("katanning", "WA", "https://www.katanning.wa.gov.au")

    def _listing_urls(self, year: int) -> list[str]:
        return [f"{self.base_url}/council-meetings/past/{year}"]

    def _summary_meeting(self, summary, listing_url, labels, year, seen):
        types = {
            self.meeting_type_of(urljoin(listing_url, link["href"]))
            for link in summary.find_all("a", href=True)
        }
        if not types & set(self.meeting_types):
            return []
        return super()._summary_meeting(summary, listing_url, labels, year, seen)
