import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_library import (
    CouncilConnectDocumentLibraryScraper,
)


@register_scraper
class YalgooScraper(CouncilConnectDocumentLibraryScraper):
    """Shire of Yalgoo—papers in the document library only.

    The meetings module exists but its meeting pages carry no documents
    (the 19 December 2025 Ordinary meeting's has none, checked 20 Oct 2026).
    Each year has an "Agendas <year>" folder; the minutes are in "Minutes
    <year>" until 2024 and in "<year> - Minutes - Audio Recordings" from
    2025, beside the recordings, so recording folders are read here (the
    recordings themselves are not PDFs and are left out). Labels carry the
    meeting's date from 2023 ("2026-05 Ordinary Council Meeting Agenda -
    Friday 29 May 2026"; the "2026-05" is a sequence number, not always the
    meeting's month). Before that most give only "2020-07 Ordinary Council
    Meeting Agenda", with no day; those are dated from their PDFs' first
    page (`pdf_dates`), taking only a day in the numbered month
    (`numbered_months`), and left out where the PDF gives none. One
    production year is three requests: every 2026 label gives its day, so
    no PDF is read.
    """

    skip_folder_pattern = re.compile(r"attach|committee|lemc", re.IGNORECASE)
    # Some meetings are held at Paynes Find, and the labels say so.
    name_noise = re.compile(r"paynes\s+find", re.IGNORECASE)

    corrections = {
        # The February 2025 Ordinary meeting was called for Friday 28
        # February (the agenda's notice) and held on 7 March 2025 (its
        # minutes, numbered "2025-02" like the agenda); there are no other
        # minutes for either month. Read 20 Oct 2026.
        "https://www.yalgoo.wa.gov.au/documents/882/2025-02-ordinary-council-meeting-agenda-and-reports-friday-28-february-2025": {
            "date": "2025-03-07"
        },
        # The 2020 and 2022 electors' meetings, labelled "2020-02 ..." and
        # "2022-04 ..." with no day: the agendas and minutes give Friday 28
        # February 2020 and Friday 29 April 2022. Read 20 Oct 2026.
        **{
            f"https://www.yalgoo.wa.gov.au/documents/{doc}": {"date": date}
            for doc, date in (
                ("605/2020-02-annual-electors-meeting-agenda", "2020-02-28"),
                ("606/2020-02-annual-electors-meeting-minutes", "2020-02-28"),
                ("727/2022-04-electors-annual-general-meeting-agenda", "2022-04-29"),
                ("740/2022-04-electors-annual-general-meeting-minutes", "2022-04-29"),
            )
        },
    }

    pdf_dates = True
    numbered_months = True

    def __init__(self):
        super().__init__("yalgoo", "WA", "https://www.yalgoo.wa.gov.au")
