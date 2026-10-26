import dataclasses
import re

from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_tidy import TidyCouncilConnectScraper

# Special meetings in 2020–2021 put their hour in the heading ("Special
# Meeting of Council - - 12:30pm", "Special Confidential Meeting of Council -
# 12.30PM") while the date field holds another: 8:50 AM for a meeting headed
# 3:30pm, 12:30 AM for one headed 12:30pm. The agendas agree with the
# heading, so where a heading names an hour, that is the meeting's time.
_HEADING_TIME = re.compile(
    r"\b(\d{1,2})(?:[:.]?(\d{2}))?\s*([ap])\.?m\b", re.IGNORECASE
)


@register_scraper
class KatherineScraper(TidyCouncilConnectScraper):
    """Katherine Town Council—CouncilConnect, documents on each meeting's page.

    Council meetings, through their two types' own year pages. The types are
    named in the plural or back to front ("Ordinary Council Meetings",
    "Special Meeting of Council"), so the names are given here in the form
    every other council uses.
    """

    meeting_types = {
        "ordinary-council-meetings": "Ordinary Council Meeting",
        "special-meeting-of-council": "Special Council Meeting",
    }
    # The /past index starts at 2017.
    first_year = 2017

    # Headings are hand-typed and vary; the type names do not.
    name_by_type = True

    wrong_documents = {
        "https://www.katherine.nt.gov.au/council-meetings/special-meeting-of-council/"
        "special-meeting-of-council-6-october-640pm/122/documents/"
        "6-october-2020-showgrounds-advisory-meeting-minutes-tbc.pdf": (
            "Minutes of the Showgrounds and Multi-Purpose Advisory Committee, "
            "6 October 2020 at 5.30pm (front page read 20 Oct 2026), filed "
            "under the 6.40pm Special Meeting of Council."
        ),
    }

    # One production year, measured 20 Oct 2026 from a home IP: 44 s (22
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 44

    def __init__(self):
        super().__init__("katherine", "NT", "https://www.katherine.nt.gov.au")

    def _name(self, heading, type_slug, labels):
        # The base names the meeting from the page heading inside
        # _meeting_from_detail; the heading is kept for the hour (above).
        self._heading = heading or ""
        return super()._name(heading, type_slug, labels)

    def _meeting_from_detail(self, url, labels, fallback_when=None):
        self._heading = ""
        meeting = super()._meeting_from_detail(url, labels, fallback_when)
        hour = _HEADING_TIME.search(self._heading)
        if meeting is not None and hour:
            hh, mm, ap = hour.groups()
            time = (
                parse_date(f"{hh}:{mm or '00'} {ap}m").strftime("%I:%M %p").lstrip("0")
            )
            meeting = dataclasses.replace(meeting, time=time)
        return meeting
