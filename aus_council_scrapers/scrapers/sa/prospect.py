"""City of Prospect.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper


@register_scraper
class ProspectScraper(LGASAFunnelbackScraper):
    listing_urls = (
        "https://www.prospect.sa.gov.au/council/council-documents/agendas-and-minutes",
    )

    # The Eastern Region Alliance is a forum of several eastern Adelaide
    # councils' mayors and CEOs, not a body of this council. Prospect
    # republishes its papers, but they are not Prospect's meetings, and the
    # same meetings would otherwise be attributed to whichever member council
    # happened to file them.
    skip_committees = frozenset({"Eastern Regional Alliance"})

    def __init__(self):
        super().__init__("prospect", "SA", "https://www.prospect.sa.gov.au")
