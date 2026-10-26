"""District Council of Karoonda East Murray.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper` and, for the
title corrections, `TitleCorrectedLGASAScraper`. Each page under
/documents/council-meetings lists one committee, so the council's page and
the Council Assessment Panel's are read, 20 s apart. The panel meets rarely
(one meeting in 2025) but it is the body that decides development
applications. The Audit and Risk, Australia Day, Youth Advisory, Roads and
Infrastructure, Wynarka Recreation and Historical Society pages would cost
one more request each and are not read.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.sa._lgasa_titles import TitleCorrectedLGASAScraper

_BRIEFING = "Information and Briefing Session"


@register_scraper
class KaroondaEastMurrayScraper(TitleCorrectedLGASAScraper):
    listing_urls = (
        "https://www.dckem.sa.gov.au/documents/council-meetings/council-agendas",
        "https://www.dckem.sa.gov.au/documents/council-meetings/development-assessment-panel-agenda-and-minutes",
    )

    # The page is named for the old Development Assessment Panel; the papers
    # are the Council Assessment Panel's ("CAP Agenda", "CDAP Minutes").
    committee_names = {
        "Development Assessment Panel Agenda & Minutes": "Council Assessment Panel",
    }

    # Informal gatherings (to 2023) and information and briefing sessions
    # (since) are filed under the council label, often on a council meeting's
    # date, and their notice otherwise became that meeting's agenda.
    #
    # The public meeting on the annual business plan and budget (section
    # 123(4) of the Local Government Act) is held the same evening as a
    # council meeting and filed under the same label. "15th July 2025 -
    # Minutes of Public Meeting" (6 pm) has a lower asset id than "15th July
    # 2025 - Special Meeting of Council Minutes" (7 pm), and was chosen as the
    # special meeting's minutes. It is a meeting of its own.
    title_bodies = (
        (re.compile(r"\binformal gathering\b", re.IGNORECASE), "Informal Gathering"),
        (re.compile(r"\bbriefing session\b", re.IGNORECASE), _BRIEFING),
        (re.compile(r"\bpublic meeting\b", re.IGNORECASE), "Public Meeting"),
    )
    # Since March 2025 a session's only paper is titled "Notice of
    # Information & Briefing Session", which names neither agenda nor
    # minutes; the notice is its agenda. Without this every session after
    # February 2025 was dropped.
    notice_committees = frozenset({_BRIEFING})

    # One production year, measured 20 Oct 2026 from a home IP: 21 s (two
    # Selenium page loads and one 20 s crawl delay between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 21

    def __init__(self):
        super().__init__("karoonda_east_murray", "SA", "https://www.dckem.sa.gov.au")
