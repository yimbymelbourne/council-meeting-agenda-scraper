"""District Council of Mount Remarkable.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`, and
`TitleRulesLGASAScraper` for the title rules. Only the council's own page is
read: the parent /documents/agenda-and-minutes is a landing page, and its
siblings are briefing sessions, informal gatherings and the Legatus Group, a
regional body of several councils.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa_titles import TitleRulesLGASAScraper


@register_scraper
class MountRemarkableScraper(TitleRulesLGASAScraper):
    listing_urls = (
        "https://www.mtr.sa.gov.au/documents/agenda-and-minutes/"
        "council-agenda-and-minutes",
    )

    # A presentation to the council, filed as an agenda paper: "Agenda 16
    # March 2021 - 2.1 Presentation - Grants Commission", filed under the
    # 15th, where it was the only paper and became a meeting.
    skip_titles = re.compile(r"presentation", re.IGNORECASE)

    # The CEO review committee's minutes, filed as a council paper.
    refile = (
        (re.compile(r"\bCE Review Committee\b", re.IGNORECASE), "CEO Review Committee"),
    )

    # Two special meetings on one day, told apart only by a mark in the
    # title, which the base class cannot read: "#1" and "#2" on 6 July 2021,
    # and on 7 July 2020 a 9.30 am meeting and one "(after 9.30 meeting)",
    # whose minutes are titled "(CEO Appointment)" (the minutes PDFs commence
    # at 9.30 am and 11.41 am). "Second" is the word the base class reads as
    # a second sitting of the same kind; see `lgasa._sitting`.
    retitle = (
        (
            re.compile(r"#\s*2\b|\(after 9\.30 meeting\)|\(CEO Appointment\)", re.I),
            "Second",
        ),
    )

    def __init__(self):
        super().__init__("mount_remarkable", "SA", "https://www.mtr.sa.gov.au")
