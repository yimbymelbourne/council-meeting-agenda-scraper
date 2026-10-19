"""City of Victor Harbor.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The "minutes
and agenda search" page is the whole collection, unfiltered: council, about
thirty committees, working and advisory groups, the Council Assessment Panel
and, since 2025, the Fleurieu Regional Assessment Panel, which Victor Harbor
administers for itself, Alexandrina, Yankalilla and Kangaroo Island. The
current year fits in the first page of 500, so production is one request.

Two corrections before assembly (see `RelabellingLGASAScraper`):

- A few documents are filed under the names of pages rather than bodies
  ("Agendas and Minutes", "Minutes and Agenda search", "Committees",
  "Minutes and Agendas"), so they take their body from the title. A
  Boating Facilities Working Group agenda under "Agendas and Minutes" was
  otherwise read as a council meeting of 25 August 2022.
- The council files resolutions released from confidence one per item,
  under "Council Meetings" and often under a date of their own:
  "CONFIDENTIAL - Strategic Land Purchase (Minutes OC3122025)", "Ordinary
  Council Meeting - Item 5.1 - Strategic Land Acquistion report & minutes".
  Filed alone they made council meetings that never happened (28 January
  2026, 12 September 2024, 28 September 2023), so they are dropped. None is
  a meeting's agenda or minutes: the public papers are filed beside them.

And one the other way. The Arts and Culture Advisory Group's agendas for
meetings moved to a new date are filed under that date and titled "Arts and
Culture Advisory Group Agenda - postponed to 10 April 2025"; they are the
agendas of the meetings held, but the base class drops any title saying
"postpone" (a cancellation notice, elsewhere). The phrase is cut from the
title, so "Agenda - 10 April 2025" is read.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.sa.lgasa_relabel import RelabellingLGASAScraper


@register_scraper
class VictorHarborScraper(RelabellingLGASAScraper):
    listing_urls = (
        "https://www.victor.sa.gov.au/your-council/council-documents/"
        "council-and-committee-meetings/minutes-and-agenda-search",
    )

    committee_names = {
        "Information or Briefing Sessions": "Information or Briefing Session",
    }

    title_labels = frozenset(
        {
            "Agendas and Minutes",
            "Minutes and Agenda search",
            "Committees",
            "Minutes and Agendas",
        }
    )

    # "OC3122025" and "ARC202026" are the council's and the audit
    # committee's numbers for a confidential order.
    exclude_titles = re.compile(
        r"confiden|\bitems?\s*\d|\b(?:OC|ARC)\d{4,}|released from confidence",
        re.IGNORECASE,
    )

    title_fixes = ((re.compile(r"\bpostponed to\s+(?=\d)", re.IGNORECASE), ""),)

    def __init__(self):
        super().__init__("victor_harbor", "SA", "https://www.victor.sa.gov.au")
