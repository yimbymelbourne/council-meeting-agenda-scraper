"""Light Regional Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The council's
meetings index carries no listing of its own—each committee page embeds the
same collection filtered by committee—so the council-meetings page is the
one linked, and the committees wanted are read one page each.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper


@register_scraper
class LightRegionalScraper(LGASAFunnelbackScraper):
    # Light has no page over the whole collection: /yourcouncil/meetings
    # carries no listing, and each committee page lists that committee only.
    # Council and the Council Assessment Panel are read; the Audit and Risk
    # Committee and Governance Advisory Panel pages would cost one more
    # request, 20 s apart, each.
    listing_urls = (
        "https://www.light.sa.gov.au/yourcouncil/meetings/councilmeetings",
        "https://www.light.sa.gov.au/yourcouncil/meetings/cap",
    )

    def __init__(self):
        super().__init__("light_regional", "SA", "https://www.light.sa.gov.au")
