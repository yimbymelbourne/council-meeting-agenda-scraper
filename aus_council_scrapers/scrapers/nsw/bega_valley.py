import datetime

from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)

# The first meeting for which Bega Valley published PDFs, and every Council
# meeting since has them.
_PDFS_FROM = datetime.date(2026, 5, 27)


@register_scraper
class BegaValleyScraper(InfoCouncilScraper):
    # Bega Valley published its papers as InfoCouncil HTML renditions only
    # until the 27 May 2026 meeting: from 2020 to 2025, 7 of 185 rows link a
    # PDF and the rest a _WEB.htm agenda and minutes with no PDF, and the PDF
    # beside one (OC_06052026_AGN_1209_AT.PDF, OC_25032026_AGN_1205_AT.PDF)
    # answers 404. A record needs an agenda or minutes PDF
    # (`ScraperReturn.check_required_properties`), and the base class skips a
    # row without one, so those meetings cannot be emitted. Reading them would
    # need both of those to accept an HTML-only record.
    #
    # The few older rows that do link a PDF are left out too: 4 of their 7
    # links answered 404 on 20 Oct 2026 (Council 1 Feb 2023, 19 Apr 2023 and
    # 27 Nov 2024 agendas; Awards and Scholarships 21 Apr 2021 minutes), and
    # the other three are scattered papers across five years, not a history.
    # So coverage starts with 27 May 2026, the first meeting with PDFs; every
    # Council row since links them. The 6 May 2026 Council meeting just
    # before it is HTML-only, and so is one Public Forum since (23 Sep 2026);
    # both are missing for the same reason.
    #
    # Supplementary rows carry an upload stamp ("Council - Supplementary
    # uploaded 19/10/2026 18:37"), which the tidy flag strips before folding
    # them onto their meeting.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "bega_valley",
            "NSW",
            "https://www.begavalley.nsw.gov.au",
            "https://begavalley.infocouncil.biz/",
        )

    def scraper(self) -> list[ScraperReturn]:
        return [m for m in super().scraper() if m.cleaned_date >= _PDFS_FROM]
