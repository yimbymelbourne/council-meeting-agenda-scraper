from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_tidy import TidyCouncilConnectScraper


@register_scraper
class DerbyWestKimberleyScraper(TidyCouncilConnectScraper):
    """Shire of Derby-West Kimberley—documents on each meeting's own page.

    Council meetings only: the Audit, Risk and Improvement Committee and the
    annual general meeting are left out, because each meeting is a request
    and they add nothing on planning.

    The agendas are whole packets with their attachments bundled in (the
    December 2025 one is 103 MB); that is the council's only agenda file.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }
    # The /past index starts at 2016; nothing older is in the module.
    first_year = 2016

    # The 29 June 2022 meeting was held at Kupungarri, a remote community on
    # the Gibb River Road, at 11:00am, as its minutes' front page says (read
    # 20 Oct 2026); the page's date field has the usual 5:30 PM.
    page_corrections = {
        "https://www.sdwk.wa.gov.au/council-meetings/ordinary-council-meeting/"
        "ordinary-council-meeting-june/144": {
            "time": "11:00 AM",
            "why": "the minutes give 11:00am",
        },
    }

    # Headings are hand-typed and vary; the type names do not.
    name_by_type = True

    # One production year, measured 20 Oct 2026 from a home IP: 24 s (13
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 24

    def __init__(self):
        super().__init__("derby_west_kimberley", "WA", "https://www.sdwk.wa.gov.au")
