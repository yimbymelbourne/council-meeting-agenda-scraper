from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import ELECTORS_NAMES, CouncilConnectScraper

_MEETINGS = "https://www.northam.wa.gov.au/council-meetings"


@register_scraper
class NorthamScraper(CouncilConnectScraper):
    """Shire of Northam—documents on each meeting's own page.

    Council meetings and the electors' meeting only, through their own year
    pages. The all-types listing runs to five pages a year: Council Forums
    (a councillor briefing a week before each Ordinary meeting, 12 in 2025),
    the audit, bush fire, CEO review and community grants committees. Each
    meeting costs a request, so reading them would put a production year
    near 50 requests.

    The type slugs are `ordinary-meeting` and `special-meeting`, not the
    usual `...-council-meeting`. Council Forums are sometimes filed under
    `ordinary-meeting` too ("Council Forum Meeting - 10 September 2025");
    the base skips a heading that names a forum before fetching its page.

    Every document label starts with a dotted date ("2025.12.17 - AGENDA -
    Ordinary Council Meeting", and unpadded "28.1.2026 - AGENDA"), which
    the base used to mistake for a report's item number, dropping every
    meeting since about 2019. Agendas are often "Part 1" files; Part 1 is
    the public agenda (Part 2 is confidential and not published).

    The date field's time is sometimes when the entry was saved ("5:24 PM"
    for a 5:30 pm meeting on 17 April 2024, "4:06 PM" for a 6:30 pm one on
    12 July 2023), so a time off the quarter-hour is left blank.
    """

    meeting_types = {
        "ordinary-meeting": "Ordinary Council Meeting",
        "special-meeting": "Special Council Meeting",
        "annual-electors-committee": "Annual Meeting of Electors",
    }
    first_year = 2006
    plausible_times_only = True
    # Headed "Annual Electors Meeting" in some years and "Annual Meeting of
    # Electors" in others.
    canonical_names = ELECTORS_NAMES

    # Labelled "AGENDA - Council Forum Meeting", which the forum rule throws
    # away, but each is the Ordinary meeting's own agenda: page 1 of both
    # reads "Agenda Ordinary Council Meeting" with the meeting's date, and
    # the notice paper says the forum was held a week earlier to discuss it.
    accepted_documents = {
        f"{_MEETINGS}/ordinary-meeting/ordinary-council-meeting-21-february-2024"
        "/596/documents/20240221-agenda-council-forum-meeting-(public).pdf": "agenda",
        f"{_MEETINGS}/ordinary-meeting/ordinary-council-meeting-15-july-2020"
        "/363/documents/20200715-agenda-council-forum-meeting-public-website.pdf": (
            "agenda"
        ),
    }

    # One production year, measured 20 Oct 2026 from a home IP: 38 s (20
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 38

    def __init__(self):
        super().__init__("northam", "WA", "https://www.northam.wa.gov.au")
