from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_library import (
    CouncilConnectDocumentLibraryScraper,
)


@register_scraper
class MorawaScraper(CouncilConnectDocumentLibraryScraper):
    """Shire of Morawa—papers in the document library only.

    The meetings module lists meetings from 2018 but their pages carry no
    documents (the 15 December 2025 Ordinary meeting's has none, checked
    20 Oct 2026). Each year has "<year> Agendas" and "<year> Minutes"
    folders, labelled with the full date ("29 September 2026 Ordinary
    Council Meeting Agenda"), beside
    "<year> Attachments" and "<year> Minutes - Recordings" folders, which
    are not read. The audit committee has a folder of its own, also not
    read. Before October 2020 most labels give the month only ("July 2020
    Ordinary Council Meeting Agenda"), and those meetings are left out.
    One production year is three requests.
    """

    # The 2022 and 2023 electors' meetings, labelled only "2022 Annual
    # Electors Meeting Agenda" and so on. The covers give Thursday 10
    # February 2022 (the 2022 minutes are a scan, read by OCR) and Wednesday
    # 25 January 2023. Read 20 Oct 2026.
    corrections = {
        f"https://www.morawa.wa.gov.au/documents/{doc}": {"date": date}
        for doc, date in (
            ("12002/2022-annual-electors-meeting-agenda", "2022-02-10"),
            ("12006/2022-annual-electors-meeting-confirmed-minutes", "2022-02-10"),
            ("12117/2023-annual-electors-meeting-agenda", "2023-01-25"),
            ("12123/2023-annual-electors-meeting-minutes", "2023-01-25"),
        )
    }

    def __init__(self):
        super().__init__("morawa", "WA", "https://www.morawa.wa.gov.au")
