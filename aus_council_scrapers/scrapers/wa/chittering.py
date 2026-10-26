import dataclasses
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_tidy import TidyCouncilConnectScraper

# Headings lead with the month instead of a date ("February Ordinary Meeting
# of Council"); the date is on the page. The month is not part of the name.
_LEADING_MONTH = re.compile(
    r"^\s*(?:January|February|March|April|May|June|July|August|September"
    r"|October|November|December)\s+",
    re.IGNORECASE,
)


@register_scraper
class ChitteringScraper(TidyCouncilConnectScraper):
    """Shire of Chittering—documents on each meeting's own page.

    Council meetings only. The monthly Agenda Forum, a councillor briefing,
    is its own meeting type and its pages carry no papers; it and the
    committee meetings would each cost a request for nothing.

    The shire takes the agenda down once the minutes are up, so a past
    meeting has its minutes only, and an agenda is caught only while the
    meeting is upcoming.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    # Two meeting pages carry the date their minutes were uploaded in the date
    # field ("Thursday, October 17, 2024 - 02:39 PM"), and their headings
    # name only the month. The minutes' front pages give the meeting: "7pm,
    # Wednesday 16 October 2024" and "7pm, Wednesday 17 July 2024" (read 20
    # Oct 2026), which also match their filenames (161024, 170724).
    redated = {
        "https://www.chittering.wa.gov.au/council-meetings/ordinary-council-meeting/"
        "october-ordinary-meeting-of-council/269": ("2024-10-16", "7:00 PM"),
        "https://www.chittering.wa.gov.au/council-meetings/ordinary-council-meeting/"
        "july-ordinary-meeting-of-council/265": ("2024-07-17", "7:00 PM"),
    }

    # One production year, measured 20 Oct 2026 from a home IP: 21 s (12
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 21

    def __init__(self):
        super().__init__("chittering", "WA", "https://www.chittering.wa.gov.au")

    def _name(self, heading, type_slug, labels):
        return super()._name(_LEADING_MONTH.sub("", heading or ""), type_slug, labels)

    def _meeting_from_detail(self, url, labels, fallback_when=None):
        meeting = super()._meeting_from_detail(url, labels, fallback_when)
        if meeting is not None and url in self.redated:
            date, time = self.redated[url]
            meeting = dataclasses.replace(meeting, date=date, time=time)
        return meeting
