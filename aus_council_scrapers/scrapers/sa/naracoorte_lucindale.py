"""Naracoorte Lucindale Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper` and
`RegionalLGASAScraper`. One page lists the whole collection—council, its
committees, the Naracoorte Regional Livestock Exchange Board (a council
subsidiary) and the Northern Limestone Coast Regional Assessment Panel—so
one request covers a production year.

Committee labels are the short names of their pages ("CEO", "Audit &
Risk"), so they are mapped to meeting types. The council's briefing notices
are informal gatherings, at which no decisions may be made, and are
skipped. So are the released confidential items, "Council Minutes Items
20.1 & 20.2 - 26 May 2026 - ...": a few are filed on a day of their own and
became meetings that never happened, and none is ever a meeting's agenda or
minutes.

Titles give the date as "2022-03-22" or "2026.09.22", and twice in 2022
both papers of a council meeting were filed days from it (22 March 2022
under the 17th); `RegionalLGASAScraper` reads those dates.

The audit committee became the Audit & Risk Committee in 2023, and its
papers moved from the label "Audit" to "Audit & Risk"—except the agenda of
its first meeting under the new name, 13 April 2023, left under "Audit"
while its minutes went under "Audit & Risk". Grouped by label, that meeting
came back as two. So a paper under "Audit" whose title names the Audit &
Risk Committee is read as filed under "Audit & Risk".
"""

import dataclasses
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa_regional import RegionalLGASAScraper


_AUDIT_AND_RISK = re.compile(r"\baudit\s*(?:&|and)\s*risk\b", re.IGNORECASE)


@register_scraper
class NaracoorteLucindaleScraper(RegionalLGASAScraper):
    listing_urls = (
        "https://www.naracoortelucindale.sa.gov.au/council/agendas-and-minutes",
    )

    committee_names = {
        "Strategic Asset & Planning": "Strategic Asset & Planning Committee",
        "Strategic Asset Management": "Strategic Asset & Planning Committee",
        "Audit & Risk": "Audit & Risk Committee",
        "Audit": "Audit Committee",
        "CEO": "CEO Committee",
        # The asterisk marks bodies the council's page lists as former ones.
        "*Council Assessment Panel": "Council Assessment Panel",
        "*Strategic Planning & Development Policy": (
            "Strategic Planning & Development Policy Committee"
        ),
    }

    skip_committees = frozenset({"Council Briefing Notices"})

    skip_titles = re.compile(r"\bitems?\s*\d", re.IGNORECASE)

    def _relabel(self, listed, year):
        if listed.committee == "Audit" and _AUDIT_AND_RISK.search(listed.title):
            return dataclasses.replace(listed, committee="Audit & Risk")
        return listed

    def __init__(self):
        super().__init__(
            "naracoorte_lucindale", "SA", "https://www.naracoortelucindale.sa.gov.au"
        )
