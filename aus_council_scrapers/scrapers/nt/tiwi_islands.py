from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_filtered import (
    FilteredListingCouncilConnectScraper,
)


@register_scraper
class TiwiIslandsScraper(FilteredListingCouncilConnectScraper):
    """Tiwi Islands Regional Council—documents on each meeting's own page.

    Council meetings only. More than half of a year's ~30 meetings are the
    three Local Authorities (Milikapiti, Pirlangimpi, Wurrumiyanga), their
    special meetings, and the audit and risk committee. The Local
    Authorities advise the council on their communities and decide no
    planning matters, and reading them would take a production year to
    about 40 requests. The module starts in 2019.

    Meeting slugs are generic (`/ordinary-council-meeting/183`), so names
    and dates come from the page, as the base does anyway.
    """

    # One production year: 17 requests, 33 s from a home connection
    # (20 Oct 2026), most of it the 2 s per-host delay.
    expected_seconds = 33
    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    def __init__(self):
        super().__init__("tiwi_islands", "NT", "https://www.tiwiislands.nt.gov.au")
