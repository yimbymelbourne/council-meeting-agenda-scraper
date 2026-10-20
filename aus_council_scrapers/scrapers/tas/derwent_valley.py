"""Derwent Valley Council (TAS).

A Tasmanian council hosted on the LGA SA shared Squiz Matrix platform, and
publishing into the same kind of Funnelback collection as the SA councils,
rendered by the same listing page, under the same robots.txt. So it is an
`LGASAFunnelbackScraper` like them, and is behind the same Cloudflare
challenge.

Everything is filed under one committee, "Council Agenda and Minutes", so the
kind of meeting comes from the document titles: the AGM is usually held the
same evening as the December council meeting, which the base class splits
into two meetings.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper


@register_scraper
class DerwentValleyScraper(LGASAFunnelbackScraper):
    listing_urls = (
        "https://www.derwentvalley.tas.gov.au/council/council-meetings/"
        "minutes-and-agendas",
    )

    def __init__(self):
        super().__init__(
            "derwent_valley", "TAS", "https://www.derwentvalley.tas.gov.au"
        )
