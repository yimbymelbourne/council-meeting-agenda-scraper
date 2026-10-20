from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_small_shires import (
    SmallShireCouncilConnectScraper,
)


@register_scraper
class WanderingScraper(SmallShireCouncilConnectScraper):
    """Shire of Wandering—documents on each meeting's own page.

    Council and electors' meetings. A year lists up to 25 meetings, and in
    2025 nine of them were the Community Centre Upgrade Committee; that, the
    audit committee and the CEO review committee are skipped by heading,
    which keeps a year near 15–19 requests instead of 30.

    Headings are a bare month ("September Ordinary Council Meeting") or a
    bare date ("11 December 2025"), so names come from the meeting type.
    """

    # Each checked by reading it (20 Oct 2026): the minutes of the 3 August
    # 2023 Special meeting, which that meeting's own page also carries.
    wrong_documents = {
        "https://www.wandering.wa.gov.au/council-meetings/ordinary-council-meeting"
        "/16-march-2023/474/documents/signed-minutes-3-august-2023-scm.pdf": (
            "the 3 August 2023 Special meeting's minutes"
        ),
        "https://www.wandering.wa.gov.au/council-meetings/special-council-meeting"
        "/4-august-2022-special-council-meeting/459/documents"
        "/signed-minutes-3-august-2023-special-meeting.pdf": (
            "the 3 August 2023 Special meeting's minutes"
        ),
        # Not another meeting's: this link returns HTTP 500 on every try
        # (checked 20 Oct 2026). The same page also lists "Minutes October
        # 2023 Signed", which returns the PDF, so that copy is taken instead.
        "https://www.wandering.wa.gov.au/council-meetings/ordinary-council-meeting"
        "/19-october-2023/496/documents/19-october-2023-minutes.pdf": (
            "a broken link; the signed copy on the same page works"
        ),
    }

    corrected_dates = {
        # Headed and dated Friday 19 August 2022. The agenda's notice gives
        # Thursday 18 August 2022 at 3.30pm, and the minutes are of the
        # meeting held 18 August 2022.
        "https://www.wandering.wa.gov.au/council-meetings/ordinary-council-meeting"
        "/19-august-2022/461": ("2022-08-18", "3:30 PM", "agenda and minutes"),
    }

    # One production year, measured 20 Oct 2026 from a home IP: 27 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 27

    def __init__(self):
        super().__init__("wandering", "WA", "https://www.wandering.wa.gov.au")
