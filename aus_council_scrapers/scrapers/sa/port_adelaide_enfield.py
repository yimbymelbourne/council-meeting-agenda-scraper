"""City of Port Adelaide Enfield.

An LGA SA Funnelback collection; everything about fetching and assembling is
in `LGASAFunnelbackScraper`. Council meetings were filed under "Full Council"
until mid-2025 and under "Agendas and minutes" since, and both labels are
read as the council itself.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper


@register_scraper
class PortAdelaideEnfieldScraper(LGASAFunnelbackScraper):
    listing_urls = ("https://www.cityofpae.sa.gov.au/council/agendas-and-minutes",)

    def __init__(self):
        super().__init__(
            "port_adelaide_enfield", "SA", "https://www.cityofpae.sa.gov.au"
        )
