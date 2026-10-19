"""Port Pirie Regional Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The "Full
Council" document library is the whole collection, unfiltered, so the
council and its committees—including the Upper Spencer Gulf Regional
Assessment Panel, which Port Pirie shares with Port Augusta and Whyalla—come
in one request.

Strategic workshops and information or briefing sessions are filed as
notices of the session ("Strategic Workshop - 13 May 2026", filed as
"Public-Notice-of-Strategic-Workshop-13-May-2026.pdf"), under the session's
own date. Each notice is that session's agenda, as Walkerville's are.

Two Asset Management Committee papers of 2022 are filed under "Council
Committees", the name of a page, so documents under that label take their
body from the title (see `RelabellingLGASAScraper`). And the notice of the
Access and Inclusion Reference Group meeting of 24 February 2026 is filed
under "Information or Briefing Sessions"; it is moved to the group's own
label.

Notices that a meeting was adjourned for want of a quorum ("Notice of
Adjournment of Committee Meeting 9 November 2020"; about twenty since 2019)
are dropped by `RelabellingLGASAScraper`: they are not agendas.
"""

import re


from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.sa.lgasa_relabel import RelabellingLGASAScraper


@register_scraper
class PortPirieScraper(RelabellingLGASAScraper):
    listing_urls = ("https://www.pirie.sa.gov.au/document-library/full-council",)

    committee_names = {
        "Information or Briefing Sessions": "Information or Briefing Session",
        "Informal Gatherings": "Informal Gathering",
        "Access & Inclusion Reference Group Meetings": (
            "Access & Inclusion Reference Group"
        ),
    }
    notice_committees = frozenset(
        {"Information or Briefing Sessions", "Informal Gatherings"}
    )

    title_labels = frozenset({"Council Committees"})
    relabel = (
        (
            "Information or Briefing Sessions",
            re.compile(r"Access (?:and|&) Inclusion Reference Group", re.IGNORECASE),
            "Access & Inclusion Reference Group Meetings",
        ),
    )

    def __init__(self):
        super().__init__("port_pirie", "SA", "https://www.pirie.sa.gov.au")
