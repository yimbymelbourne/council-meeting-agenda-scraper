"""Kentish Council (TAS).

A Tasmanian council hosted on the LGA SA shared Squiz Matrix platform, like
Derwent Valley, so it is an `LGASAFunnelbackScraper` behind the same
Cloudflare challenge and robots.txt. Every meeting is filed under "Full
Council", so special meetings and AGMs are told apart by their titles
("Minutes of Special Meeting on 4 May 2026").
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper

# Filed under "Full Council" beside the meetings, and neither an agenda nor
# minutes: "At Council's Last Meeting", the council's one-page newsletter of
# each meeting's decisions, and the agenda of a community information
# evening on local government reform ("Agenda LG Reform Kentish CIE 20 July
# 2023"). The newsletter was otherwise taken for the agenda of a meeting on
# 28 February 2023 that never sat, and the evening for a council meeting.
_NOT_A_MEETING = re.compile(
    r"\bat\s+council'?s\s+last\b|\bCIE\b|community\s+information\s+evening",
    re.IGNORECASE,
)


@register_scraper
class KentishScraper(LGASAFunnelbackScraper):
    listing_urls = ("https://www.kentish.tas.gov.au/council/minutes-and-agendas",)

    def __init__(self):
        super().__init__("kentish", "TAS", "https://www.kentish.tas.gov.au")

    def _assemble(self, documents, year):
        return super()._assemble(
            [d for d in documents if not _NOT_A_MEETING.search(d.title)], year
        )
