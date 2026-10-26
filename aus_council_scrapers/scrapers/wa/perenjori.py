from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_small_shires import (
    SmallShireCouncilConnectScraper,
)


@register_scraper
class PerenjoriScraper(SmallShireCouncilConnectScraper):
    """Shire of Perenjori—documents on each meeting's own page.

    Council and electors' meetings; the audit committee is skipped by
    heading (see `SmallShireCouncilConnectScraper`). The agenda is posted as one
    packet, "Agenda & Attachments", which is the only agenda there is.

    The 18 December 2025 Special meeting is headed "Special Meeting of
    Council - 18 November 2025". Its date field and both its documents say
    18 December, so the field's date stands (the base checks this).
    """

    # Checked by reading it (20 Oct 2026): a scan of the 20 October 2022
    # Ordinary meeting's minutes, the same file as that meeting's own, posted
    # on the 27 October Special meeting, which then has no papers of its own.
    wrong_documents = {
        "https://www.perenjori.wa.gov.au/council-meetings/special-council-meeting"
        "/special-council-meeting-27th-october-2022/617/documents"
        "/confirmed-minutes-october-ocm.pdf": "the 20 October 2022 Ordinary minutes",
    }

    corrected_dates = {
        # Headed 28th, dated Friday 29 July in the field; the minutes (a
        # scan, read by OCR) are of the meeting of 28 July 2022. The field's
        # 11:00 AM is not trusted either.
        "https://www.perenjori.wa.gov.au/council-meetings/special-council-meeting"
        "/special-council-meeting-28th-july-2022/616": (
            "2022-07-28",
            None,
            "minutes",
        ),
    }

    # One production year, measured 20 Oct 2026 from a home IP: 23 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 23

    def __init__(self):
        super().__init__("perenjori", "WA", "https://www.perenjori.wa.gov.au")
