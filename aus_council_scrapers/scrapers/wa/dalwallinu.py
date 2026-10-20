from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_filtered import (
    FilteredListingCouncilConnectScraper,
)


@register_scraper
class DalwallinuScraper(FilteredListingCouncilConnectScraper):
    """Shire of Dalwallinu—documents on each meeting's own page.

    Council meetings only. A year runs to ~22 meetings, a third of them the
    audit, bush fire advisory and local emergency management committees;
    reading them took 2025 to 25 requests. The module starts in 2020.

    Dalwallinu's per-type year pages drop meetings: on 20 Oct 2026
    /ordinary-council-meeting/past/2026 listed 3 of the 8 Ordinary meetings
    held so far, and its 2020 and 2022 pages each missed one. Hence the
    all-types listing (see councilconnect_filtered).
    """

    # One production year: 13 requests, 24 s from a home connection
    # (20 Oct 2026), most of it the 2 s per-host delay.
    expected_seconds = 24
    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }
    # The 24 March 2020 meeting's page carries the February agenda, whose
    # cover says "Ordinary Council Agenda February 2020" (read 20 Oct 2026).
    # It is also on the 25 February meeting's own page.
    wrong_documents = {
        "https://www.dalwallinu.wa.gov.au/council-meetings/ordinary-council-meeting"
        "/ordinary-council-meeting-24-march-2020/30/documents/"
        "ocm-agenda-25-february-2020.pdf": "the 25 February 2020 agenda",
    }

    def __init__(self):
        super().__init__("dalwallinu", "WA", "https://www.dalwallinu.wa.gov.au")
