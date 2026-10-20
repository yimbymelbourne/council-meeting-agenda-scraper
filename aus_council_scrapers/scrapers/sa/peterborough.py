"""District Council of Peterborough.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. Until
September 2025 the council published each meeting's papers as a one-page
"Council NOM" (notice of meeting) and a "Council Report", the full business
paper with the agenda index and every report; neither title says "agenda".
Information sessions, briefing sessions and workshops are filed under the
same label as council meetings and are read as bodies of their own.

A special meeting's Report is sometimes only the report itself: the 1 July
2025 "Special Council Meeting Report" opens on "EXECUTIVE & GOVERNANCE
REPORT … 4.1 CEO ANNUAL LEAVE", and the agenda list (present, apologies,
items) is only in the scanned NOM beside it. The Report is still taken as
the agenda, because it holds the business the meeting decided and the NOM
holds nothing more than the list.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper


@register_scraper
class PeterboroughScraper(LGASAFunnelbackScraper):
    # Peterborough's council page lists the whole collection; the page name
    # is also the committee label.
    listing_urls = (
        "https://www.peterborough.sa.gov.au/our-council/meeting-dates,-reports-and-minutes/council",
    )

    committee_names = {
        "Council Meeting Agenda, Reports & Minutes": "Council Meeting",
        "Council Meeting Agendas, Reports & Minutes": "Council Meeting",
    }

    body_from_title = (
        (r"information session|\bNOIS\b", "Information Session"),
        (r"briefing session", "Briefing Session"),
        (r"informal gathering", "Informal Gathering"),
        (r"workshop", "Council Workshop"),
    )
    # The business paper ("Council Report 17/03/25", "Sp Council Report",
    # "Special Council Meeting Report - Annual Business Plan 25-26") is the
    # agenda, ranked ahead of everything else: ahead of the one-page NOM,
    # which the base class reads as a notice of meeting, and ahead of a paper
    # titled "Agenda". Until mid-2021 the council filed both a "Council
    # Agenda 17/08/20" (three pages: the notice and the agenda index) and a
    # "Council Report 17/08/20 v2" (98 pages: the same index and every
    # report). Level ranks would fall to the lower asset id, the short one.
    # No meeting since September 2025 has a Report, so this never displaces
    # the "Council Meeting Agenda" papers published since.
    # Single reports filed beside it ("CEO Report - Delegations", "Works
    # Report - Late") do not match. A session's notice ("Notice of
    # Information Session 17/03/25", "Notice of Informal Gathering 12/07/21 -
    # Closed to Public") is its agenda and its "Notes" are its minutes. Slide
    # decks presented at workshops are never either.
    title_kinds = (
        (r"[Pp]resentation", None, 0),
        (r"^(?:Special |Sp )?(?:Counci?l? )?(?:Meeting )?Report\b", "agenda", -1),
        (r"\bNotes\b", "minutes", 1),
        (r"^Notice of (?:Information Session|Informal Gathering)", "agenda", 1),
    )

    # A paper filed alone under a day its title and file name both
    # contradict was filed under its publication day; see `_restated_date`.
    restate_lone_dates = True

    def __init__(self):
        super().__init__("peterborough", "SA", "https://www.peterborough.sa.gov.au")
