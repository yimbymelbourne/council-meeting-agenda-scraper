from urllib.parse import urljoin

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.wheatbelt_councilconnect import (
    WheatbeltCouncilConnectScraper,
)


@register_scraper
class KulinScraper(WheatbeltCouncilConnectScraper):
    """Shire of Kulin—documents on each meeting's own page.

    Council meetings only. The other types are the audit committee (filed
    under two type names) and the electors' meeting, neither of which
    decides planning matters; leaving them out saves a request each per
    meeting.

    The base reads a `meeting_types` council through its per-type year
    pages, but Kulin's Ordinary type has none: /council-meetings/
    ordinary-council-meeting/past/<year> 404s for every year from 2020 to
    2026, while the Special type's answers. The base takes a current-year
    404 to mean the year has no meetings yet, so the per-type route would
    lose every Ordinary meeting without a word. The all-types listing is
    read instead, one request per ten meetings, and a meeting filed under
    any other type is skipped before its page is fetched.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    # The date field says Saturday 18 January 2020; the agenda is "to be
    # held 18 November 2020" (read 20 Oct 2026).
    corrected_dates = {
        "https://www.kulin.wa.gov.au/council-meetings/ordinary-council-meeting/ordinary-council-meeting-november-2020/21": "2020-11-18",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 26 s
    # (13 requests—the year listings, the upcoming page and a page per
    # meeting). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 26

    def __init__(self):
        super().__init__("kulin", "WA", "https://www.kulin.wa.gov.au")

    def _listing_urls(self, year: int) -> list[str]:
        return [f"{self.base_url}/council-meetings/past/{year}"]

    def _summary_meeting(self, summary, listing_url, labels, year, seen):
        for link in summary.find_all("a", href=True):
            type_slug = self.meeting_type_of(urljoin(listing_url, link["href"]))
            if type_slug:
                if type_slug not in self.meeting_types:
                    return []
                break
        return super()._summary_meeting(summary, listing_url, labels, year, seen)
