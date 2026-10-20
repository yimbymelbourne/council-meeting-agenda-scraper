"""District Council of Coober Pedy.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper` and, for the
title corrections, `TitleCorrectedLGASAScraper`. The agendas-and-minutes page
lists only the council's own meetings, under one label ("Council Agendas and
Minutes"). Its Audit and Risk Committee and CEO Performance Review Committee
have a listing page each, which would cost one more request, 20 s apart,
apiece; neither is read. The council has no assessment panel of its own.

From 2020 to early 2022 most meetings have their minutes here but no
agenda; the council did not publish the agendas in this collection.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.sa._lgasa_titles import TitleCorrectedLGASAScraper

_BRIEFING = "Information and Briefing Session"


@register_scraper
class CooberPedyScraper(TitleCorrectedLGASAScraper):
    listing_urls = (
        "https://www.cooberpedy.sa.gov.au/council/meetings/minutes-and-agendas",
    )

    # Briefing-session notices are filed under the council label, and one
    # ("Briefing session - Monday 27 November 2023") otherwise stood in for
    # the agenda of the council meeting five days before it.
    title_bodies = ((re.compile(r"\bbriefing\s+session\b", re.IGNORECASE), _BRIEFING),)
    # The notice is the session's only paper, so it is its agenda.
    notice_committees = frozenset({_BRIEFING})

    def __init__(self):
        super().__init__("coober_pedy", "SA", "https://www.cooberpedy.sa.gov.au")
