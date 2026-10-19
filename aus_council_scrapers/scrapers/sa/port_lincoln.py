"""City of Port Lincoln.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The listing
covers the whole collection, so every committee comes in one request.

Council meetings are filed under "Ordinary Council Meeting", which the base
class does not read as the council by itself. The Eyre Peninsula Regional
Assessment Panel is filed under "Minutes & Agendas", the name of the page,
along with a few council minutes, so documents under that label take their
body from the title (see `RelabellingLGASAScraper`).

Information and briefing sessions are filed only as notices, each of which
is that session's agenda, as Walkerville's are. Every one since 2020 starts
its title with the session's date, "9/2/2026 - Closed to Public - Elected
Member Workshop - State election proposal", and 72 of the 76 are filed
under that date too. The other four are filed up to a fortnight early (that
one under 3 February; the notice inside says Monday 9 February 2026), so
these notices are dated by their titles (see `RelabellingLGASAScraper`).
Two sessions on one day are one record, with the first notice uploaded as
its agenda.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import COUNCIL_MEETING
from aus_council_scrapers.scrapers.sa.lgasa_relabel import RelabellingLGASAScraper


@register_scraper
class PortLincolnScraper(RelabellingLGASAScraper):
    listing_urls = ("https://www.portlincoln.sa.gov.au/council/minutes-and-agendas",)

    committee_names = {
        "Ordinary Council Meeting": COUNCIL_MEETING,
        "Information/Briefing Sessions": "Information or Briefing Session",
    }
    notice_committees = frozenset({"Information/Briefing Sessions"})
    title_dated_committees = frozenset({"Information/Briefing Sessions"})

    title_labels = frozenset({"Minutes & Agendas"})
    drop_stray_years = True
    title_bodies = (
        (
            re.compile(r"\bEPRAP\b|Eyre Peninsula Regional Assessment", re.IGNORECASE),
            "Eyre Peninsula Regional Assessment Panel",
        ),
    )

    def __init__(self):
        super().__init__("port_lincoln", "SA", "https://www.portlincoln.sa.gov.au")
