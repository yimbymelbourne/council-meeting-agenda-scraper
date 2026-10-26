"""Town of Gawler.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. This is the
collection that taught the base class most of its caution: cancellation
notices and item attachments filed as Agendas, 422 documents with no category
at all, and CAP minutes whose date was never set and sits on 1 January.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper


@register_scraper
class GawlerScraper(LGASAFunnelbackScraper):
    listing_urls = (
        "https://www.gawler.sa.gov.au/our-council/meetings/agendas-and-minutes",
    )

    def __init__(self):
        super().__init__("gawler", "SA", "https://www.gawler.sa.gov.au")
