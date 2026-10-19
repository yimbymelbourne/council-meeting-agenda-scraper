from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import ELECTORS_NAMES, CouncilConnectScraper


@register_scraper
class MooraScraper(CouncilConnectScraper):
    """Shire of Moora—documents on each meeting's own page.

    The meetings module starts in 2025: /past lists 2025 and 2026 only, and
    earlier years 404. Older papers are in the site's document library
    ("Minutes and Agendas Prior to 2025"), which this does not read.

    Council meetings only; the audit committee (filed under two types,
    `audit-committee` and `audit-commitee`) is left out. The electors'
    meeting is filed under the Special type and comes with it. An Ordinary
    meeting's page also carries the same evening's Briefing Session and
    Audit Committee agendas, which are never taken as its agenda.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-meeting-of-council": "Special Council Meeting",
    }
    first_year = 2025
    # The 4 June 2025 electors' meeting's field says "11:36 AM".
    plausible_times_only = True
    canonical_names = ELECTORS_NAMES

    # Filed and headed as an Ordinary meeting, but its agenda and minutes are
    # those of a Special Council Meeting (the post-election swearing-in and
    # election of the Shire President), checked by reading the agenda. The
    # module lists no other meeting that October.
    corrections = {
        "https://www.moora.wa.gov.au/council-meetings/ordinary-council-meeting"
        "/29-october-2025-ordinary-meeting-of-council/13": {
            "name": "Special Council Meeting"
        },
    }

    # One production year, measured 20 Oct 2026 from a home IP: 28 s (15
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 28

    def __init__(self):
        super().__init__("moora", "WA", "https://www.moora.wa.gov.au")
