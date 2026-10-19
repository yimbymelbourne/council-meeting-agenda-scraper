"""Copper Coast Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The listing
covers the whole collection—council, the Council Assessment Panel and the
audit committee—so one request reads them all.

Council meetings are filed under "Ordinary Council", which the base class
does not read as the council by itself. The audit committee became the
Audit & Risk Committee in 2022, and that year's agendas sit under the old
label while their minutes sit under the new one, so both labels are one
body here.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import COUNCIL_MEETING, LGASAFunnelbackScraper


@register_scraper
class CopperCoastScraper(LGASAFunnelbackScraper):
    listing_urls = ("https://www.coppercoast.sa.gov.au/council/agendas-and-minutes",)

    committee_names = {
        "Ordinary Council": COUNCIL_MEETING,
        "Audit Committee": "Audit and Risk Committee",
        "Audit & Risk Committee": "Audit and Risk Committee",
    }

    def __init__(self):
        super().__init__("copper_coast", "SA", "https://www.coppercoast.sa.gov.au")
