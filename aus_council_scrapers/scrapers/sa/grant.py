"""District Council of Grant, now Southern Limestone Coast Council.

The council titles itself Southern Limestone Coast Council and has moved to
www.slcc.sa.gov.au; www.dcgrant.sa.gov.au redirects there. The slug stays
`grant`.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. There is no
page over the whole collection, so the committees wanted are read one page
each: ordinary (and special) council meetings, and the Limestone Coast
Southern Regional Assessment Panel, which has decided development
applications since 2022. The Council Assessment Panel before it has a
listing that stopped in 2022, so it is read only for those years; see
`RegionalLGASAScraper`. The Planning & Development Committee's listing
stopped in 2019, before `EARLIEST_YEAR`, and is not read.

Two special meetings were held on 27 January 2022, at 5.30 pm and 6.30 pm,
and their agendas have the same title ("27 January 2022 Special Meeting
Agenda"). Only the file names give the start times, and only the minutes'
titles say "First Meeting" and "Second Meeting". The base class kept one
meeting and paired the 6.30 pm agenda with the 5.30 pm minutes (checked
against both PDFs' first pages), so `RegionalLGASAScraper` pairs them by
start time (see `_pair_numbered_sittings`).
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import COUNCIL_MEETING
from aus_council_scrapers.lgasa_regional import RegionalLGASAScraper

LCSRAP = "Limestone Coast Southern Regional Assessment Panel"


@register_scraper
class GrantSAScraper(RegionalLGASAScraper):
    listing_urls = (
        "https://www.slcc.sa.gov.au/council/meetings/ordinary",
        "https://www.slcc.sa.gov.au/council/meetings/regional-assessment-panel",
    )

    historic_listings = (("https://www.slcc.sa.gov.au/council/meetings/cap", 2022),)

    committee_names = {
        # Special meetings are filed here too; the titles say which.
        "Ordinary Council Meetings": COUNCIL_MEETING,
        "Regional Assessment Panel": LCSRAP,
    }

    # One production year, measured 20 Oct 2026 from a home IP: 21 s (2
    # Selenium page loads and one 20 s crawl delay between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 21

    def __init__(self):
        super().__init__("grant", "SA", "https://www.slcc.sa.gov.au")
