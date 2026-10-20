"""District Council of Barunga West.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`, and
`TitleRulesLGASAScraper` for the title rules. There is no page over the
whole collection: council papers and each committee's are on pages of their
own (under /documents/committee-meetings/). The council's page and its
Council Assessment Panel's, the body that decides development applications,
are read; the audit, executive, governance and town committees would cost a
listing page and a 20 s crawl delay each.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa_titles import TitleRulesLGASAScraper


@register_scraper
class BarungaWestScraper(TitleRulesLGASAScraper):
    listing_urls = (
        "https://www.barungawest.sa.gov.au/documents/council-agenda-and-minutes",
        "https://www.barungawest.sa.gov.au/documents/committee-meetings/"
        "cap-agenda-and-minutes",
    )

    # One production year, measured 20 Oct 2026 from a home IP: 21-22 s,
    # two Selenium page loads and one 20 s crawl delay between them. Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 22

    # The panel's page name is its label; the base class would shorten it
    # to "CAP".
    committee_names = {"CAP Agenda & Minutes": "Council Assessment Panel"}

    # Not a meeting's agenda:
    # - a single report's attachment, titled with the agenda it belongs to:
    #   "2025.04.08 Meeting Agenda - 10.3 A3 Table of Delegations" (item
    #   10.3, attachment A3), which outranked that meeting's real agenda, and
    #   "Apr 09 2024 Agenda - Separate Cover 10.11 A2".
    # - "Apr 28 2023 Special Council Meeting Agenda (Conf. order lifted)"
    #   (?a=1338359), which is not an agenda: it is a three-page copy of
    #   that meeting's minutes ("MINUTES of Special Council Meeting"),
    #   filed with the minutes re-released below. Kept, it would replace
    #   the real agenda.
    skip_titles = re.compile(
        r"\b\d{1,2}\.\d{1,2}\s*A\d+\b|separate cover"
        r"|Agenda\s*\(Conf\.?\s*order lifted\)",
        re.IGNORECASE,
    )

    # The 28 April 2023 special meeting's minutes were published with its
    # confidential item withheld, then filed again in full once the
    # confidentiality order was lifted on 8 May 2023. The full minutes
    # replace the first version; without this the base class read "Conf
    # order lifted" as naming a second sitting that day and emitted the
    # meeting twice.
    supersede = re.compile(r"\s*\(Conf\.?\s*order lifted\)", re.IGNORECASE)

    # Committee minutes filed on the council's page, in its early years.
    # "March 24 2020 Executive Committee Meeting Minutes" had become the
    # minutes of that day's special council meeting.
    refile = (
        (re.compile(r"\bExecutive Committee\b", re.IGNORECASE), "Executive Committee"),
        (re.compile(r"\bAudit Committee\b", re.IGNORECASE), "Audit Committee"),
        (
            re.compile(r"\bGAP\b|Governance Advisory Panel", re.IGNORECASE),
            "Governance Advisory Panel",
        ),
    )

    # Titles lead with the meeting's date, month first ("Feb 09 2021
    # Ordinary Council Meeting Minutes"), and several papers are filed a
    # month off it: those minutes under 9 January, the 13 June 2023 agenda
    # under 13 July. See `title_dates`.
    title_dates = True

    def __init__(self):
        super().__init__("barunga_west", "SA", "https://www.barungawest.sa.gov.au")
