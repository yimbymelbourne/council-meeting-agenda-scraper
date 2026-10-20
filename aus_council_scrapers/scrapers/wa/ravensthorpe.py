from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_filtered import (
    FilteredListingCouncilConnectScraper,
)


@register_scraper
class RavensthorpeScraper(FilteredListingCouncilConnectScraper):
    """Shire of Ravensthorpe—documents on each meeting's own page.

    Council meetings only, which leaves out the audit committee and the
    electors' meeting (two or three a year).

    In 2020 every Ordinary meeting was filed under a type of its own,
    "Ordinary Council Meeting - 2020", and two 2021 meetings under "... -
    2021". They are the same meetings, so they are listed here under the
    plain name. Reading the all-types listing means these cost nothing in
    the years they are empty.
    """

    # One production year: 17 requests, 32 s from a home connection
    # (20 Oct 2026), most of it the 2 s per-host delay.
    expected_seconds = 32
    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "ordinary-council-meeting-2020": "Ordinary Council Meeting",
        "ordinary-council-meeting-2021": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    def __init__(self):
        super().__init__("ravensthorpe", "WA", "https://www.ravensthorpe.wa.gov.au")
