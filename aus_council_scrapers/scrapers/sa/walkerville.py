"""Town of Walkerville.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. Its committee
labels are page names ("Council Agendas and Minutes", "CEO Performance
Review Committee Agendas & Minutes"), which the base class strips back to the
body's name—including the CEO committee, which is filed under both "&" and
"and" spellings.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper


@register_scraper
class WalkervilleScraper(LGASAFunnelbackScraper):
    # The agendas index lists the whole collection; each page under it
    # (council-agendas-and-minutes, ...) lists one committee.
    listing_urls = ("https://www.walkerville.sa.gov.au/council/council/agendas",)

    # The documents filed here are notices of "Information/Briefing Session"s;
    # "Informal Gatherings" is the page they are listed on, not a meeting type.
    committee_names = {"Informal Gatherings": "Information and Briefing Session"}
    # Those notices are the sessions' agendas whatever they are titled
    # ("Elected Member Briefing Session Notice 9 February 2023").
    notice_committees = frozenset({"Informal Gatherings"})

    # ERA Water is a stormwater-reuse regional subsidiary of Walkerville,
    # Burnside and Campbelltown, with its own board. Walkerville republishes
    # its papers, but its board meetings are not Walkerville's meetings.
    skip_committees = frozenset({"ERA Water"})

    def __init__(self):
        super().__init__("walkerville", "SA", "https://www.walkerville.sa.gov.au")
