import re

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.armidale.nsw.gov.au"


@register_scraper
class ArmidaleScraper(OpenCitiesContentScraper):
    # One page, every meeting from 2022, no accordions: each meeting is a
    # paragraph headed by its name and date in bold ("Ordinary Council
    # Meeting - Wednesday 23 September 2026") with its papers below, each
    # titled with the date again ("Ordinary Meeting Agenda - Wednesday 23
    # September 2026", "Adopted OCM Minutes - ..."). Attachment books,
    # late attachments, item attachments and councillors' questions on the
    # agenda ("QON") sit beside every agenda and are not it; an agenda
    # "(incl Attachments)" is.
    pages = [ContentPage(f"{_BASE_URL}/Council/Meetings-agendas-and-minutes")]
    not_the_paper = re.compile(r"\bquestions?\b|\bqons?\b", re.IGNORECASE)

    def __init__(self):
        super().__init__("armidale", "NSW", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> str:
        # The minutes say "OCM" and "ECM" where the agendas say "Ordinary
        # Meeting" and "Extraordinary Meeting"; spell them out so the two
        # papers of a meeting carry one name. "Adopted" minutes are the
        # confirmed set, "Draft" the unconfirmed one.
        label = re.sub(r"\bOCM\b", "Ordinary Meeting", label)
        label = re.sub(r"\bECM\b", "Extraordinary Meeting", label)
        return re.sub(r"\badopted\b", "Confirmed", label, flags=re.IGNORECASE)
