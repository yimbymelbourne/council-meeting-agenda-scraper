import re
from urllib.parse import urlparse

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.ionata import IonataMeetingsScraper

# Glenorchy City Council. Eight cards a page, so a year is two to four pages.
# The archive goes back to 2016; 2016-2025 documents were re-uploaded in July
# 2026, which is why old meetings link to uploads/2026/07/.
#
# Some agendas are published as one PDF with their attachments
# ("...-Open-Agenda-and-Attachments.pdf"). That is the agenda as the council
# issues it, so it is kept. Cards linking attachments separately label them
# "Attachments", which is ignored.

_SPECIAL_FILE = re.compile(r"_EXTRA\b|\bspecial\b", re.IGNORECASE)


@register_scraper
class GlenorchyScraper(IonataMeetingsScraper):
    listing_url = "https://www.gcc.tas.gov.au/your-council/council-meetings/meeting-schedule/"
    card_selector = "div.card-meeting"
    title_selector = ".card-meeting__title"
    date_selector = ".card-meeting__date"
    location_selector = ".card-meeting__location"

    def __init__(self):
        super().__init__("glenorchy", "TAS", "https://www.gcc.tas.gov.au")

    def meeting_name(self, card: Tag, title: str, documents: list[str]) -> str:
        # Unlike its neighbours, Glenorchy prints the meeting type on the card
        # ("Council Meeting", "Glenorchy Planning Authority", "Special Council
        # Meeting", "Annual General Meeting").
        category = card.select_one(".card-meeting__category")
        name = category.get_text(" ", strip=True) if category else ""
        if not name:
            name = "Council Meeting"
        if "meeting" not in name.lower():
            name = f"{name} Meeting"
        # The category is wrong on a few special meetings, but their files
        # still say so. Special meetings were filed as OC_<date>_AGN_EXTRA.pdf
        # through 2025 and as "...-Special-Council-meeting-agenda.pdf" in 2026.
        # Three cards filed that way are categorised "Council Meeting" (18 May
        # 2020, 19 June 2020, 21 June 2021), and all three agendas are headed
        # "SPECIAL COUNCIL MEETING AGENDA".
        if name == "Council Meeting" and any(
            _SPECIAL_FILE.search(urlparse(url).path.rsplit("/", 1)[-1])
            for url in documents
        ):
            name = "Special Council Meeting"
        return name
