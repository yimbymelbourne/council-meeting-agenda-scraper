"""Latrobe Council (TAS).

A Tasmanian council hosted on the LGA SA shared Squiz Matrix platform, like
Derwent Valley, and publishing into the same kind of Funnelback collection
under the same robots.txt; see `LGASAFunnelbackScraper`. Its listing is the
one LGA SA page here that answers a Cloudflare challenge even to a home
connection, which the base class's Selenium fetch, with the "HeadlessChrome"
token stripped, clears.

Everything is filed under one label, "Minutes & Agenda", which the base
class does not read as the council by itself (its page-name rule expects
"Agendas and Minutes"). Only council meetings are filed there; special
meetings are named as such only in their file names
("Agenda-Special-Meeting-7-September-2026-inline.pdf" for "Agenda - 7
September 2026"), so that is where the kind is read from (see
`RelabellingLGASAScraper`); the AGMs say so in their titles. A "Revised
Agenda" filed beside the original (28 April 2025) replaces it.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import COUNCIL_MEETING
from aus_council_scrapers.scrapers.sa.lgasa_relabel import RelabellingLGASAScraper


@register_scraper
class LatrobeTasScraper(RelabellingLGASAScraper):
    listing_urls = (
        "https://www.latrobe.tas.gov.au/council/publications/minutes-and-agenda",
    )

    committee_names = {"Minutes & Agenda": COUNCIL_MEETING}
    special_from_filename = True

    def __init__(self):
        super().__init__("latrobe_tas", "TAS", "https://www.latrobe.tas.gov.au")
