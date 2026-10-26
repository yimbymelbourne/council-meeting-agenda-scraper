import datetime
from typing import Optional

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectScraper
from aus_council_scrapers.scrapers.wa.councilconnect_shires import (
    ShireCouncilConnectScraper,
)

SITE = "https://www.meekashire.wa.gov.au"
_PLANNING_COMMITTEE = "health-building-and-town-planning-meeting"


@register_scraper
class MeekatharraScraper(ShireCouncilConnectScraper):
    """Shire of Meekatharra—documents on each meeting's own page.

    Council meetings and the Health, Building and Town Planning Committee,
    which met monthly in 2022–2024 and took the planning reports. The audit
    committee and the electors' meeting are left out to save a request per
    meeting. The committee has not met since 2024, so its listing costs one
    request a production year and finds nothing; that is the price of its
    26 meetings of planning history (27 listed, one of them twice).

    The site names its types in the plural ("Ordinary Council Meetings",
    "Special Meetings"), and the base would emit that as each meeting's
    name; with `meeting_types` set, the names below win. Meeting slugs are
    generic (`/ordinary-council-meeting/350`), so dates come from the page,
    which the base does anyway.

    Agendas were not uploaded for most of 2020.
    """

    meeting_types = {
        "ordinary-council-meetings": "Ordinary Council Meeting",
        "special-meetings": "Special Council Meeting",
        _PLANNING_COMMITTEE: "Health, Building and Town Planning Committee Meeting",
    }

    # Read 20 Oct 2026: the agenda, filed under "Agenda" but labelled as one
    # of its attachments.
    relabelled_documents = {
        f"{SITE}/council-meetings/ordinary-council-meetings/ordinary-council-meeting"
        "/355/documents/20251025-ordinary-council-meeting-agenda.pdf": "Agenda",
    }

    # The committee's 16 December 2022 meeting is listed twice: page 290
    # (1 pm, agenda and unconfirmed minutes) and page 289 (2 pm, minutes
    # only). Both minutes read "... Town Planning Meeting ... 16 December
    # 2022 commencing at 1.00pm", unconfirmed; this one only corrects the
    # weekday. Leaving it out leaves page 289 with nothing, so the meeting
    # is emitted once, from page 290.
    wrong_documents = {
        f"{SITE}/council-meetings/{_PLANNING_COMMITTEE}"
        "/health-building-and-town-planning-committee-meeting/289/documents"
        "/minutes-hbtp-december-2022-v2.pdf": (
            "a second copy of the 16 December 2022 committee minutes, on a "
            "duplicate listing of that meeting"
        ),
    }

    # One production year, measured 20 Oct 2026 from a home IP: 25 s for
    # 14 requests (the type listings, one per Council meeting of the year
    # and the upcoming page). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 25

    def __init__(self):
        super().__init__("meekatharra", "WA", SITE)

    def _summary_meeting(self, summary, listing_url, labels, year, seen):
        # With `meeting_types` set, the base skips a listing entry whose
        # heading names a committee, so that a committee filed under a
        # Council type is not fetched. Here the committee is the point:
        # every entry on its own listing is headed "Health, Building & Town
        # Planning Committee Meeting", and the base would skip all 27.
        if f"/{_PLANNING_COMMITTEE}/" not in listing_url:
            return super()._summary_meeting(summary, listing_url, labels, year, seen)
        types = self.meeting_types
        self.meeting_types = None  # the heading test is all this disables
        try:
            return super()._summary_meeting(summary, listing_url, labels, year, seen)
        finally:
            self.meeting_types = types

    @staticmethod
    def _link_date(link) -> Optional[datetime.date]:
        # The upcoming page's buttons say only "View Meeting Details", so
        # the base cannot tell how far off a meeting is and fetches every
        # one listed. The date is in the <strong> above the button
        # ("Saturday, November 21, 2026").
        date = CouncilConnectScraper._link_date(link)
        if date:
            return date
        info = link.find_parent(class_="council-meeting-info")
        if info is None:
            return None
        return CouncilConnectScraper._parse_when(info.get_text(" ", strip=True))[0]
