import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import ELECTORS_NAMES, CouncilConnectScraper

_MEETINGS = "https://www.leonora.wa.gov.au/council-meetings"


@register_scraper
class LeonoraScraper(CouncilConnectScraper):
    """Shire of Leonora—documents on each meeting's own page.

    Council meetings and the electors' meeting; the audit committee (four a
    year) is left out to keep a production year near 15 requests. The
    all-types listing is two pages a year, cheaper than three per-type
    pages, so it is read and filtered by type (`type_listings = False`).

    Leonora heads about half its Ordinary meetings "Ordinary Council
    Committee Meeting"—the minutes inside are "Minutes of the Ordinary
    Council Meeting"—so a heading naming a committee is not skipped here, and
    the name comes from the type, not the heading. It has also filed two
    special audit committee meetings under the Special Council type ("Special
    Audit Risk Committee Meeting - 18 February 2020", "Special Meeting of the
    Audit Committee - 20 April 2021"); a heading naming the audit committee
    is skipped.

    Some date fields hold the time the entry was saved ("2:25 PM" and "1:35
    PM" for 9.30 am meetings in 2022), and five say "12:00 AM", so times off
    the quarter-hour or outside the working day are left blank. Two minutes
    are labelled "Confirmed MINS ..." (16 and 25 July 2024), which the base
    reads as minutes.
    """

    meeting_types = {
        "ordinary-council-meetings": "Ordinary Council Meeting",
        "special-council-meetings": "Special Council Meeting",
        "electors-meeting": "Annual Meeting of Electors",
    }
    type_listings = False
    plausible_times_only = True
    # Every page under the electors' type is an annual meeting (2021–2026).
    canonical_names = ELECTORS_NAMES
    not_a_council_meeting = re.compile(r"forum|briefing|audit", re.IGNORECASE)

    # On the quarter-hour, but not what the agenda's notice says: the
    # electors' meetings of 16 March 2021 and 15 February 2022 were called
    # for 2:00pm (fields 1:15 PM and 3:00 PM), and the Ordinary meeting of
    # 19 October 2021 for 9:30am (field 1:30 PM). The 17 February 2026
    # electors' meeting repeats the same morning's Ordinary meeting's 10:00
    # AM; its minutes say it opened at 11:11am after that meeting, and the
    # agenda gives no time, so it is left blank.
    corrections = {
        f"{_MEETINGS}/electors-meeting/electors-meeting-16-march-2021/264": {
            "time": "2:00 PM"
        },
        f"{_MEETINGS}/electors-meeting/annual-electors-meeting-2021/286": {
            "time": "2:00 PM"
        },
        f"{_MEETINGS}/ordinary-council-meetings"
        "/ordinary-council-meeting-19th-october-2021/269": {"time": "9:30 AM"},
        f"{_MEETINGS}/electors-meeting/annual-electors-meeting-17-february-2026/364": {
            "time": None
        },
    }

    # One production year, measured 20 Oct 2026 from a home IP: 28 s (15
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 28

    def __init__(self):
        super().__init__("leonora", "WA", "https://www.leonora.wa.gov.au")

    def _name(self, heading, type_slug, labels):
        # Every meeting read is one of the three types above, and the
        # headings add nothing but the "Committee" slip and the date.
        return self.meeting_types.get(type_slug) or super()._name(
            heading, type_slug, labels
        )
