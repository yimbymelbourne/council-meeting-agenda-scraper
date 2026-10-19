import re
from urllib.parse import urlparse

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.ionata import IonataMeetingsScraper

# Clarence City Council, on Hobart's eastern shore. Not to be confused with
# Clarence Valley (NSW), which is the `clarence` tenant on api.resolve.red—
# its agendas are headed "Grafton" and its ordinary meetings fall on Thursday
# mornings, where Clarence City meets on Monday evenings.
#
# Twelve cards a page; a year is two pages.
#
# About three in ten agendas (39 of 135 across 2020-2026, every year) are not
# on the asset host but shared from the council's Pydio Cells server
# (resources.ccc.tas.gov.au/public/<hash>). That URL is a JavaScript viewer,
# not the PDF, and the file behind it is only reachable through a logged-in
# session whose download links expire within the hour. Those meetings keep
# their minutes and go without an agenda, rather than store a viewer page as
# if it were the document—`document_url` refuses anything not ending .pdf.
#
# Titles are typed by hand ("Clarence City Council Meeting – 12 October 2026",
# "Special Council Meeting (Planning Authority)", "Clarence City Council – AGM"),
# so the meeting type is read from keywords. The rules mirror the site's own
# Meeting Type filter: Annual General, Planning Authority, Special, Council.
#
# The keywords are looked for in the agenda and minutes filenames as well as
# the title, because each sometimes says what the other leaves out. The 10 June
# 2025 card is titled "Clarence City Council Meeting" and links
# Special-Council-Meeting-Agenda-10-June-2025.pdf, and that agenda is headed
# "SPECIAL COUNCIL MEETING". Several cards titled "Special Council Meeting"
# link Planning-Authority agendas or minutes. Their agendas are headed
# "CLARENCE CITY COUNCIL (PLANNING AUTHORITY)", the same as the meetings
# titled "Planning Authority". They are one body, so they get one name.
_NAME_RULES = (
    (re.compile(r"annual[\s-]general|\bagm\b", re.IGNORECASE), "Annual General Meeting"),
    (re.compile(r"planning[\s-]authority", re.IGNORECASE), "Planning Authority Meeting"),
    (re.compile(r"\bspecial\b", re.IGNORECASE), "Special Council Meeting"),
)


@register_scraper
class ClarenceScraper(IonataMeetingsScraper):
    listing_url = "https://www.ccc.tas.gov.au/your-council/council-meetings/agendas-minutes/"
    card_selector = "div.content-card"
    title_selector = ".content-card__title"
    date_selector = ".content-card__info > div:nth-of-type(1)"
    location_selector = ".content-card__info > div:nth-of-type(2)"

    def __init__(self):
        super().__init__("clarence", "TAS", "https://www.ccc.tas.gov.au")

    def meeting_name(self, card: Tag, title: str, documents: list[str]) -> str:
        filenames = [urlparse(url).path.rsplit("/", 1)[-1] for url in documents]
        text = " ".join([title, *filenames])
        for pattern, name in _NAME_RULES:
            if pattern.search(text):
                return name
        return "Council Meeting"
