"""City of Port Augusta.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The agendas
and minutes page is the whole collection, unfiltered: council, the Upper
Spencer Gulf Regional Assessment Panel (shared with Port Pirie and Whyalla),
the audit committee, briefing sessions and advisory groups. Council meetings
are filed under "Council Meeting Agendas & Minutes", which the base class
reads as the council.

Briefing sessions are filed only as notices ("Briefing Session Notice 20
October 2026"), under the session's own date; each is that session's
agenda, as Walkerville's are.

Most committees publish an agenda and no minutes, so their meetings carry
an agenda only: that is what the council publishes, not a pairing failure.
The Disability, Aboriginal Community and Great Western Bridge Timbers
advisory groups publish one PDF per meeting, "Agenda & Minutes - 03/02/2025":
the agenda, then that meeting's minutes. It is both the agenda and the
minutes (`combined_documents`; see `RelabellingLGASAScraper`).
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.sa.lgasa_relabel import RelabellingLGASAScraper


@register_scraper
class PortAugustaScraper(RelabellingLGASAScraper):
    listing_urls = (
        "https://www.portaugusta.sa.gov.au/the-council/agendas-and-minutes",
    )

    committee_names = {"Briefing Sessions": "Briefing Session"}
    notice_committees = frozenset({"Briefing Sessions"})
    combined_documents = True

    def __init__(self):
        super().__init__("port_augusta", "SA", "https://www.portaugusta.sa.gov.au")
