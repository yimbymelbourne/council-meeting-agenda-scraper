"""Kangaroo Island Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The council
files everything under one committee label, "Council Meetings": its ordinary
and special meetings, its Audit and Risk Committee, its information briefing
sessions (called informal gatherings until 2021) and its budget workshops.
So the body that met is read from each document's title (`body_from_title`)
rather than from the label, which would make every briefing session a
council meeting.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper


@register_scraper
class KangarooIslandScraper(LGASAFunnelbackScraper):
    # The site's only listing: the collection holds one committee label, so
    # this page is the whole of it.
    listing_urls = (
        "https://www.kangarooisland.sa.gov.au/council/publications-and-documents/councilmeetings",
    )

    # Searched in order; a title naming none of these is a council meeting.
    # "Breifing" is the council's own spelling on 28 May 2026, and
    # "Information/Briefing" its spelling in 2023.
    body_from_title = (
        (r"\baudit\b", "Audit and Risk Committee"),
        (r"\binformation\W*br(?:ie|ei)fing\b", "Information Briefing Session"),
        (r"\binformal\b", "Informal Gathering"),
        (r"\bworkshop\b", "Budget Workshop"),
        # The annual business plan's public consultation meeting ("2025-06-26
        # Draft Annual Business Plan and Budget Public Meeting").
        (r"\bpublic meeting\b", "Public Meeting"),
    )
    # A briefing session's only paper is often its notice ("Information
    # Briefing Notice 2026-09-24"), which is that session's agenda. So is the
    # budget public meeting's: "Public Meeting draft ABP and Budget
    # FY2026-2027 Notice 2026-07-22" names neither agenda nor minutes, and is
    # not worded as a "notice of meeting".
    notice_committees = frozenset(
        {"Information Briefing Session", "Informal Gathering", "Public Meeting"}
    )

    # A paper filed alone under a day its title and file name both
    # contradict was filed under its publication day; see `_restated_date`.
    restate_lone_dates = True

    def __init__(self):
        super().__init__(
            "kangaroo_island", "SA", "https://www.kangarooisland.sa.gov.au"
        )
