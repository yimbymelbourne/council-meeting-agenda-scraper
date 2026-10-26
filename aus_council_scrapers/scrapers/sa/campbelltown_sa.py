"""Campbelltown City Council (SA).

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. Over a third
of its documents are meeting audio ("Recording"), which the base class never
treats as an agenda or minutes.

The class is `CampbelltownSAScraper`, not `CampbelltownScraper`: that name is
the NSW council's, and `SCRAPER_REGISTRY` is keyed by class name, so reusing
it would silently replace one council with the other.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper


@register_scraper
class CampbelltownSAScraper(LGASAFunnelbackScraper):
    # The whole collection. The council-and-committees/council page lists
    # only the Council committee.
    listing_urls = (
        "https://www.campbelltown.sa.gov.au/council/documents-and-publications/"
        "minutes-and-agendas",
    )

    def __init__(self):
        super().__init__("campbelltown_sa", "SA", "https://www.campbelltown.sa.gov.au")
