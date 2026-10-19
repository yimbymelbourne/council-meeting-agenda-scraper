import re
from urllib.parse import unquote, urlparse

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_filtered import (
    FilteredListingCouncilConnectScraper,
)

# "Notice of Special Council Meeting" (4 April 2022) and "Notice of Special
# Council Meeting - 6 July 2021" (read 20 Oct 2026): one page each, a letter
# to councillors saying when the meeting sits and naming its business in a
# bullet or two, with no reports or recommendations. A notice of meeting,
# not an agenda.
_NOTICE_OF_MEETING = re.compile(
    r"notice[\s_-]+of[\s_-]+(?:special[\s_-]+)?(?:council[\s_-]+)?meeting",
    re.IGNORECASE,
)


@register_scraper
class MerredinScraper(FilteredListingCouncilConnectScraper):
    """Shire of Merredin—documents on each meeting's own page.

    Council meetings only. The Audit Committee meets most months on the same
    day as Council, so reading it would add about six requests a year and
    take a production year past 25.

    Each meeting's Attachments group carries the previous meeting's minutes
    ("Attachment 7.1A Minutes - ..."); the base never reads an attachment
    group, so they are not mistaken for this meeting's.
    """

    # One production year: 13 requests, 25 s from a home connection
    # (20 Oct 2026), most of it the 2 s per-host delay.
    expected_seconds = 25
    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }
    # The 27 July 2021 special meeting's page carries the minutes of the 6
    # July special meeting, whose cover says "Tuesday, 6 July 2021" (read
    # 20 Oct 2026). The same minutes are on the 6 July meeting's own page.
    wrong_documents = {
        "https://www.merredin.wa.gov.au/council-meetings/special-council-meeting"
        "/special-council-meeting/175/documents/"
        "special-council-meeting-minutes-6-july-2021-(public).pdf": (
            "minutes of the 6 July 2021 special meeting"
        ),
    }

    def __init__(self):
        super().__init__("merredin", "WA", "https://www.merredin.wa.gov.au")

    def _pick_documents(self, links):
        # A notice of meeting is never taken as the agenda. Of the two seen,
        # 6 July 2021 still has its minutes and stays; 4 April 2022 has
        # nothing else and drops out, which also keeps out a date the notice
        # contradicts (the page says Monday 4 April, the notice Tuesday 5
        # April, and no minutes settle it).
        return super()._pick_documents(
            [
                (group, label, url)
                for group, label, url in links
                if not _NOTICE_OF_MEETING.search(
                    f"{label} {unquote(urlparse(url).path.rsplit('/', 1)[-1])}"
                )
            ]
        )
