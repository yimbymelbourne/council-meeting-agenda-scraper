from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.wheatbelt_councilconnect import (
    WheatbeltCouncilConnectScraper,
)


@register_scraper
class KondininScraper(WheatbeltCouncilConnectScraper):
    """Shire of Kondinin—documents on each meeting's own page.

    Council meetings only. Every committee—audit, infrastructure, medical
    and community services, emergency management—is filed under one
    "Committee Meetings" type, and 2026 ran to 28 requests reading every
    type. None of those committees decides planning matters. The type
    slugs are plural ("ordinary-council-meetings"), so the names are given
    here in the singular.

    The type's name is used (`name_by_type`), because the Special
    headings are hand-typed variations ("Budget Adoption- Special Council
    Meeting", "Special Budget Meeting 27th May 2026", "Tuesday 7
    February"), checked across 2022–2026 on 20 Oct 2026. Committees are
    sometimes filed under the Special type too: in 2026 the "Behavior
    Complaints Committee Meeting 11th February 2026" and the "Audit Risk &
    Improvement Committee Meeting 10th February 2026". Those are not
    Special Council meetings. They are left out only because the base skips
    any listing heading that says "committee" before fetching its page
    (`_NOT_A_COUNCIL_MEETING`). A committee whose heading did not say so
    would be emitted as a Special Council Meeting.
    """

    meeting_types = {
        "ordinary-council-meetings": "Ordinary Council Meeting",
        "special-council-meetings": "Special Council Meeting",
    }

    name_by_type = True

    # Read 20 Oct 2026: labelled "Ordinary Council Meeting Minutes - April
    # 2025 CONFRIMED", but the minutes of the meeting held 19 March 2025,
    # with no mention of April. The March page has its own copy.
    wrong_documents = {
        "https://www.kondinin.wa.gov.au/council-meetings/ordinary-council-meetings/16-april-2025-ordinary-council-meeting/141/documents/minutes-march-2025-website.pdf": (
            "Minutes of 19 March 2025, posted as the 16 April 2025 minutes"
        ),
    }

    # Read 20 Oct 2026: the date field says Wednesday 18 June 2025, but the
    # heading says 25 June, the agenda says the meeting "will be held in
    # Council Chambers on 25th June 2025", and the minutes say it was held
    # then. The base's heading check cannot settle it, because the
    # filenames name only the month ("ordinary-council-meeting-agenda-
    # june-2025.pdf").
    corrected_dates = {
        "https://www.kondinin.wa.gov.au/council-meetings/ordinary-council-meetings/25-june-2025-ordinary-council-meeting/143": "2025-06-25",
    }

    # The /past index starts at 2022, and /past/2020 and /past/2021 404,
    # which would fail the whole scrape.
    first_year = 2022

    # One production year, measured 20 Oct 2026 from a home IP: 32 s
    # (17 requests—the year listings, the upcoming page and a page per
    # meeting). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 32

    def __init__(self):
        super().__init__("kondinin", "WA", "https://www.kondinin.wa.gov.au")
