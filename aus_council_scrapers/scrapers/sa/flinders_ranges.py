"""The Flinders Ranges Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`, and
`TitleRulesLGASAScraper` for the title rules. The council's meetings page
and the Flinders Regional Development Assessment Panel's, which assesses
development applications for the council and its neighbours, are read. The
whole-collection page (/council/agendas, 1,824 documents) is not: over 40%
of it is the town and progress reference committees, and the visitor
centre, audit and Legatus Group papers would come with them.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa_titles import TitleRulesLGASAScraper


@register_scraper
class FlindersRangesScraper(TitleRulesLGASAScraper):
    listing_urls = (
        "https://www.frc.sa.gov.au/council/agendas/"
        "ordinary-and-special-meetings-of-council",
        "https://www.frc.sa.gov.au/council/agendas/"
        "flinders-regional-development-assessment-panel",
    )

    # One production year, measured 20 Oct 2026 from a home IP: 21-22 s,
    # two Selenium page loads and one 20 s crawl delay between them. Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 22

    # The page's name, used as the label of every council paper. It names
    # both kinds of meeting, so without this a special meeting could not be
    # called one.
    committee_names = {"Ordinary & Special Meetings of Council": "Council Meeting"}

    # Filed as council papers but not a council meeting's:
    # - workshops and the 2020 consultative session on the business plan:
    #   informal gatherings under s 90A of the Local Government Act 1999
    #   (SA), at which no decision may be made. Each became a "Council
    #   Meeting" on a day the council did not meet.
    # - "WRRC Agenda 10 September 2025", a reference committee's agenda,
    #   which became a council meeting with no minutes.
    # - "S90(3)(a) Confidential Minutes", the confidential part only,
    #   released later.
    skip_titles = re.compile(
        r"workshop|consultative session|^WRRC\b|confidential", re.IGNORECASE
    )

    # Each agenda is filed twice: "- Agenda Only", the order of business, and
    # "- Agenda, Reports & Attachments", the full papers. The base class
    # drops the second as an attachment. Read without the suffix, the full
    # papers are the agenda, and the order of business is used only for a
    # meeting whose full papers were not filed (2025-26 special meetings,
    # some years' ordinary ones).
    retitle = (
        (
            re.compile(
                r"\s*-\s*Agenda,?\s*Reports?\s*(?:&|and)?\s*Attachments\s*$", re.I
            ),
            "",
        ),
    )
    # The panel's titles sometimes omit "Agenda Only" ("FRAP Agenda 23
    # November 2021"), and the file name says it instead.
    demote = re.compile(r"\bAgenda[\s_-]+Only\b", re.IGNORECASE)

    # "FRC Special Meeting Minutes 26 October 2020" is filed under 26
    # January, nine months off and beside nothing, where it was a meeting
    # that never happened. Every other paper of 2020 on whose date the title
    # and the listing disagree is either within the base class's fortnight
    # or titled with another year, so trusting the title this far moves only
    # that one; see `title_dates`.
    title_dates = True
    title_date_window_days = 366

    def __init__(self):
        super().__init__("flinders_ranges", "SA", "https://www.frc.sa.gov.au")
