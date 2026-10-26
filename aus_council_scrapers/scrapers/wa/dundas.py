from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import ELECTORS_NAMES, CouncilConnectScraper

_MEETINGS = "https://www.dundas.wa.gov.au/council-meetings"


@register_scraper
class DundasScraper(CouncilConnectScraper):
    """Shire of Dundas—documents on each meeting's own page.

    Council and electors' meetings; the audit committee (two types, Audit
    Committee and Audit, Risk & Improvement Committee, plus a Special one)
    is left out. The electors' type has no year page of its own (404), so
    the all-types listing is read and filtered (`type_listings = False`).

    Meeting slugs are generic (`/ordinary-council-meeting/ordinary-council-
    meeting/214`), so names and dates come from the page. Each Ordinary
    meeting's page carries the previous meeting's unconfirmed minutes as an
    appendix ("App1_Unconfirmed Minutes - 29 September 2026 OCM"), which is
    never taken as its minutes, and "Papers Relating", the attachments.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
        "annual-general-meeting-of-electors": "Annual Meeting of Electors",
    }
    type_listings = False
    first_year = 2015
    # "6:00 AM" for the 6.00 pm meeting of 21 January 2021.
    plausible_times_only = True
    canonical_names = ELECTORS_NAMES

    # Checked by reading it: the unconfirmed minutes of the 28 June 2022
    # electors' meeting, posted for confirmation on the 2 March 2023
    # meeting's page, listed ahead of that meeting's own minutes.
    wrong_documents = {
        "https://www.dundas.wa.gov.au/council-meetings"
        "/annual-general-meeting-of-electors/annual-general-meeting-of-electors"
        "/154/documents/unconfirmed-minutes-annual-general-electors-meeting-28-0622.pdf": (
            "the 28 June 2022 electors' meeting's minutes, on 2 March 2023's page"
        ),
    }

    # The date field holds the notice date for this one: the agenda's notice
    # is signed 21 January 2020 for a meeting "held on 23rd January 2020",
    # and every document on the page says the 23rd. The heading is the bare
    # "Ordinary Council Meeting", so the base has no second date to weigh.
    #
    # The times below are on the quarter-hour, so `plausible_times_only`
    # keeps them, but each disagrees with its agenda's notice of meeting
    # (and, where they print one, the minutes). 19 March 2022 was held at
    # Eucla "commencing at 4pm ACWST", the local time there.
    corrections = {
        f"{_MEETINGS}/ordinary-council-meeting/ordinary-council-meeting/7": {
            "date": "2020-01-23"
        },
        f"{_MEETINGS}/ordinary-council-meeting/ordinary-council-meeting/122": {
            "time": "4:00 PM"  # field: 9:00 AM
        },
        f"{_MEETINGS}/annual-general-meeting-of-electors"
        "/annual-general-meeting-of-electors/113": {
            "time": "5:00 PM"  # field: 5:30 PM
        },
        f"{_MEETINGS}/special-council-meeting/special-council-meeting/112": {
            "time": "6:00 PM"  # field: 10:45 AM
        },
        f"{_MEETINGS}/ordinary-council-meeting/ordinary-council-meeting/89": {
            "time": "6:00 PM"  # field: 4:00 PM
        },
    }

    # One production year, measured 20 Oct 2026 from a home IP: 36 s (20
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 36

    def __init__(self):
        super().__init__("dundas", "WA", "https://www.dundas.wa.gov.au")
