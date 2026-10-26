from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_filtered import (
    FilteredListingCouncilConnectScraper,
)


@register_scraper
class ExmouthScraper(FilteredListingCouncilConnectScraper):
    """Shire of Exmouth—documents on each meeting's own page.

    Council meetings only: the audit committees, the electors' meeting and
    the occasional advisory group (Ningaloo tourism, a COVID-19 relief fund
    committee in 2020) are left out, which keeps a production year near 16
    requests. The module goes back to 2011.

    Meeting slugs are generic (`/ordinary-council-meeting/ordinary-council-
    meeting/261`), so names and dates come from the page, as the base does
    anyway. Document labels are terse ("25 12 11 Agenda") but the groups on
    the page say which is which.
    """

    # One production year: 15 requests, 28 s from a home connection
    # (20 Oct 2026), most of it the 2 s per-host delay.
    expected_seconds = 28
    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    def __init__(self):
        super().__init__("exmouth", "WA", "https://www.exmouth.wa.gov.au")
