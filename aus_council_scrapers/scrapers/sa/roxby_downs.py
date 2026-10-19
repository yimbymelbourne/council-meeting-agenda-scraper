"""Municipal Council of Roxby Downs.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. Its collection
is named `roxby-downs-council-maa-push` rather than the usual
`...-minutes-and-agenda-push`, but the page renders it the same way.
Agendas are issued as "Council Meeting Notice and Agenda".
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper

# Confidential items are released one at a time, report and minutes extract
# together ("Confidential Minutes - Council - 21 December 2022 - Sports
# Precinct Tender Evaluation and Prudential Review - Released"). Each is one
# item, never the meeting's minutes, and that one was filed a day after the
# meeting, so it came out as a council meeting of its own on 22 December.
_CONFIDENTIAL = re.compile(r"\bconfidential\b", re.IGNORECASE)


@register_scraper
class RoxbyDownsScraper(LGASAFunnelbackScraper):
    # The whole collection: Council, the audit committee and the Council
    # Assessment Panel. The pages under it list one committee each.
    listing_urls = (
        "https://www.roxbydowns.sa.gov.au/council/about-roxby-council/agendasandminutes",
    )

    def __init__(self):
        super().__init__("roxby_downs", "SA", "https://www.roxbydowns.sa.gov.au")

    def _assemble(self, documents, year):
        return super()._assemble(
            [d for d in documents if not _CONFIDENTIAL.search(d.title)], year
        )
