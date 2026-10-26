"""Coorong District Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. Titles name
only the date and the kind ("20 October 2026 - Agenda"), so the body that met
comes from the committee label.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper


@register_scraper
class CoorongScraper(LGASAFunnelbackScraper):
    # The whole collection: Council, the Coorong Assessment Panel and the
    # council's committees.
    listing_urls = ("https://www.coorong.sa.gov.au/your-council/agendas-and-minutes",)

    # Registers the council publishes into the same collection: monthly
    # development registers and credit card statements, filed under a date
    # but belonging to no meeting.
    skip_committees = frozenset(
        {
            "Development Register",
            "Credit Cards",
            "Credit Cards & Financial Delegations",
            "Credit Card Statements",
        }
    )

    # The base class follows the file name when it names a different paper
    # from the title. One exception here: "Council-Assessment-Panel-CAP-Agenda-Template-7-July-2020.pdf" is the 7 July 2020 minutes, as this module was verified with.
    title_kinds = ((r"^Council Assessment Panel - Minutes 7 July 2020$", "minutes", 0),)

    def __init__(self):
        super().__init__("coorong", "SA", "https://www.coorong.sa.gov.au")
