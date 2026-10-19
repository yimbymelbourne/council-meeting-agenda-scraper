import datetime

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_shires import (
    ShireCouncilConnectScraper,
)


@register_scraper
class KellerberrinScraper(ShireCouncilConnectScraper):
    """Shire of Kellerberrin—documents on each meeting's own page.

    Council meetings only. Every meeting costs a request, and since 2025 the
    shire files its Roadworks Advisory, LEMC and audit committees under one
    `committee-meeting` type—six of them by October 2026, which with the
    electors' meetings would push a production year past 20 requests.

    The module holds no Ordinary meetings for 2024: that year's listing has
    only a Special Council meeting and two electors' meetings, and the
    document library has none either (checked 20 Oct 2026). The 19 October
    2021 meeting has only its late-reports agenda online, which is not the
    meeting's agenda, so it is not emitted.

    Every meeting entered before May 2025 has the module's time of "6:00
    PM", which is a default and not the meeting's time. The agendas checked
    say 2 pm (16 June 2020, 17 August and 16 November 2021, 15 March and 15
    November 2022), 4 pm (20 June 2023, 18 February, 20 March and 15 April
    2025) or 8.15 am (30 March 2020, 4 November 2024); none says 6 pm.
    Those meetings are emitted with no time. From 20 May 2025 the module's
    times are the agendas' own.
    """

    placeholder_time = ("6:00 PM", datetime.date(2025, 5, 1))

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 29 s for
    # 14 requests (the type listings, one per Council meeting of the year
    # and the upcoming page). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 29

    def __init__(self):
        super().__init__("kellerberrin", "WA", "https://www.kellerberrin.wa.gov.au")
