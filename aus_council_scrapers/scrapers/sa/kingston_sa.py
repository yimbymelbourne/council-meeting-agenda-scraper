"""Kingston District Council (SA).

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`, and
`TitleRulesLGASAScraper` for the title rules. Every document is filed under
one label, "Agendas & Minutes", which the base class reads as the council
itself; the council publishes no committee papers here.

The class is `KingstonSAScraper`, not `KingstonScraper`: that name is the
Victorian council's, and `SCRAPER_REGISTRY` is keyed by class name, so
reusing it would silently replace one council with the other.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa_titles import TitleRulesLGASAScraper


@register_scraper
class KingstonSAScraper(TitleRulesLGASAScraper):
    listing_urls = (
        "https://www.kingstondc.sa.gov.au/our-council/council-meeting/"
        "agendas-and-minutes",
    )

    # A notice that a meeting was adjourned is not its agenda. The 23
    # September 2025 meeting was adjourned to the 30th, and its only paper,
    # "Notice of Adjourned Council Meeting", became an agenda-only meeting
    # beside the real one.
    skip_titles = re.compile(r"notice of adjourn", re.IGNORECASE)

    def __init__(self):
        super().__init__("kingston_sa", "SA", "https://www.kingstondc.sa.gov.au")
