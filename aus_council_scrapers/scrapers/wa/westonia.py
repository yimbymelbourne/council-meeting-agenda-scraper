import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import ELECTORS_NAMES, CouncilConnectScraper


@register_scraper
class WestoniaScraper(CouncilConnectScraper):
    """Shire of Westonia—documents on each meeting's own page.

    Every type is read: there are only Ordinary and Special meetings, about
    twelve a year, so a production year is ~12 requests.

    Westonia usually files its Audit Committee's and electors' meeting
    papers on the Ordinary meeting's page ("0325 Audit Agenda March 2025",
    "0226 Agenda Annual General Meeting of Electors 2026") rather than as
    meetings of their own. They are never taken as the Ordinary meeting's
    papers, and so those meetings are not returned (the 2021 electors'
    meeting, which has a page of its own, is). Headings name the month
    ("February Ordinary Council Meeting"), which the base strips from the
    name.

    The date field is the day the entry was made for at least one meeting:
    "February Meeting 2020" says Wednesday 19 February, while its agenda
    and minutes both say Thursday 20 February 2020. A review on 20 Oct 2026
    checked every row against page 1 of its documents and found no other.
    """

    # "February Meeting 2020" leaves the type's own "Ordinary Meeting".
    canonical_names = ELECTORS_NAMES + (
        (re.compile(r"^ordinary meeting$", re.IGNORECASE), "Ordinary Council Meeting"),
    )

    corrections = {
        "https://www.westonia.wa.gov.au/council-meetings/ordinary-meeting"
        "/february-meeting-2020/32": {"date": "2020-02-20"},
    }

    # One production year, measured 20 Oct 2026 from a home IP: 24 s (12
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 24

    def __init__(self):
        super().__init__("westonia", "WA", "https://www.westonia.wa.gov.au")

    def _meeting_from_detail(self, url, labels, fallback_when=None):
        # The time in Westonia's date field is when the entry was made, not
        # when the meeting starts: the 2020 meetings say 8:10 or 8:20 AM,
        # nearly all the 2022 ones 11:40 or 11:45 AM, and the March 2020
        # agenda says "Council Meeting – 3.30 pm". The date is right; the
        # time—from the field or the upcoming page's button, which repeats
        # it—is left blank rather than wrong.
        meeting = super()._meeting_from_detail(url, labels, fallback_when)
        if meeting is not None:
            meeting.time = None
        return meeting
