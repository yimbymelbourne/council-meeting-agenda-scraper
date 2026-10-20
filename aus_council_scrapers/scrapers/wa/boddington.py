from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_filtered import (
    FilteredListingCouncilConnectScraper,
)


@register_scraper
class BoddingtonScraper(FilteredListingCouncilConnectScraper):
    """Shire of Boddington—documents on each meeting's own page.

    Council meetings only, which leaves out the audit and local emergency
    committees and the electors' meetings and keeps a production year near
    18 requests.

    The meetings module starts in 2022: its /past index lists 2022 onward,
    and /past/2021 and /past/2020 are 404s.
    """

    # One production year: 16 requests, 30 s from a home connection
    # (20 Oct 2026), most of it the 2 s per-host delay.
    expected_seconds = 30
    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }
    first_year = 2022
    # The date field of the February 2024 meeting is the moment it was
    # entered (Friday 23 February, 3:27 pm). Its agenda and signed minutes
    # both say Thursday 15 February 2024 (read 20 Oct 2026).
    corrected_dates = {
        "https://www.boddington.wa.gov.au/council-meetings/ordinary-council-meeting"
        "/ordinary-council-meeting-february-2024/133": (
            "2024-02-15",
            "agenda and signed minutes both dated Thursday 15 February 2024",
        ),
    }

    def __init__(self):
        super().__init__("boddington", "WA", "https://www.boddington.wa.gov.au")
