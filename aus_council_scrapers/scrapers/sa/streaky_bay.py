"""District Council of Streaky Bay.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`, and
`TitleRulesLGASAScraper` for the title rules. The page read is the whole
collection (note the comma in its path), so the council's committees, its
Council Assessment Panel and the Eyre Peninsula Regional Assessment Panel
that replaced it, which assesses development applications for Streaky Bay
and its neighbours, come with it at no extra cost.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa_titles import TitleRulesLGASAScraper


@register_scraper
class StreakyBayScraper(TitleRulesLGASAScraper):
    listing_urls = (
        "https://www.streakybay.sa.gov.au/council-documents/"
        "council-minutes,-reports-and-agenda",
    )

    committee_names = {
        # The page's own name, used as a label for a few council papers in
        # 2024.
        "Council Minutes, Reports & Agenda": "Council Meeting",
        "Council Assessment Panel (CAP)": "Council Assessment Panel",
    }

    # Elected member sessions: informal gatherings under s 90A of the Local
    # Government Act 1999 (SA), at which no decision may be made.
    skip_committees = frozenset({"Informal Gatherings"})

    # The panel's annual reports, filed as its papers.
    skip_titles = re.compile(r"annual report", re.IGNORECASE)

    # The Assets and Infrastructure Advisory Committee's 12 December 2024
    # minutes, filed a second time under the page's label, where they would
    # have become a council meeting.
    refile = (
        (
            re.compile(r"Assets and Infra\w* Advisory Committee", re.IGNORECASE),
            "Assets & Infrastructure Advisory Committee",
        ),
    )

    # The 19 March 2024 agenda was filed twice, "Council Agenda - 19 March
    # 2024 - No Attachments" (69 pages: the notice, the agenda and every
    # officer's report) and "... - With Attachments" (372 pages, 47 MB, the
    # same with the reports' attachments bound in). The base class drops
    # both as attachments, because the date sits between "Agenda" and
    # "Attachments", and the meeting had no agenda. Read without the
    # suffix, both are the agenda, and the copy with the attachments ranks
    # behind the agenda itself, as the base class ranks "Agenda &
    # Attachments" behind a plain agenda. Its title loses the suffix, so
    # the file name says which it is.
    retitle = (
        (re.compile(r"\s*-\s*(?:With|No) Attachments\s*$", re.IGNORECASE), ""),
    )
    demote = re.compile(r"\bWith[\s_-]+Attachments\b", re.IGNORECASE)

    def __init__(self):
        super().__init__("streaky_bay", "SA", "https://www.streakybay.sa.gov.au")
