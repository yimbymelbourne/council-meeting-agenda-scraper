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

    # The base class follows the file name when it names a different paper
    # from the title. One exception here: "Audit-Committee-Meeting-Minutes-12.02.21.pdf" is the 12 February 2021 agenda, as this module was verified with; the minutes are filed separately.
    title_kinds = ((r"^Audit Committee Notice and Agenda - 12 February 2021$", "agenda", 0),)

    def __init__(self):
        super().__init__("roxby_downs", "SA", "https://www.roxbydowns.sa.gov.au")

    def _assemble(self, documents, year):
        return super()._assemble(
            [d for d in documents if not _CONFIDENTIAL.search(d.title)], year
        )
