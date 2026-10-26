import re

from bs4 import NavigableString, Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import OpenCitiesContentScraper

_BASE_URL = "https://www.snowymonaro.nsw.gov.au"

_AGENDA_WORDS = r"\bagendas?\b|\bbusiness(?:es)?[\s-]+papers?\b"
_KIND = re.compile(rf"{_AGENDA_WORDS}|\bminutes\b", re.IGNORECASE)
_YEAR = re.compile(r"\b20\d{2}\b")
_TYPED = re.compile(r"\b(?:ordinary|extraordinary|special)\b", re.IGNORECASE)


def _one_name(label: str) -> str:
    """Name the ordinary meeting the same way in every year.

    2020–22 labels and the 2026 h6 headings say "Council Meeting"; 2023–25
    and early 2026 say "Ordinary Council Meeting". Extraordinary meetings
    are always named, so an unnamed Council meeting is the ordinary one.
    """
    if _TYPED.search(label):
        return label
    return re.sub(r"\bCouncil Meeting\b", "Ordinary Council Meeting", label, count=1)


@register_scraper
class SnowyMonaroScraper(OpenCitiesContentScraper):
    # A page per year from 2016 ("Business-Papers-and-Minutes-2026"), linked
    # from the Meetings page, each with a "Business Papers <year>" and a
    # "Minutes <year>" heading. The business paper is the agenda. Up to 2025
    # every link carries its meeting ("Ordinary Council Meeting — 20
    # November 2025 — Business Paper"); from 2026 a business paper is only
    # "Business Paper" under an h6 naming the meeting, and a set of minutes
    # "Confirmed Minutes" after the meeting written into the list item.
    #
    # Attachments, supplementary and late papers, amended reports, questions
    # on the business paper, confidential minutes and the public forum's
    # minute record sit beside the papers and are none of them.
    year_index = f"{_BASE_URL}/Council/Meetings"
    year_page = re.compile(
        r"/Council/Meetings/Business-Papers-and-Minutes-(?P<year>\d{4})$"
    )
    page_headings = ("h2", "h3")
    agenda_words = _AGENDA_WORDS
    not_the_paper = re.compile(r"\bquestions?\b|\bpublic\s+forum\b", re.IGNORECASE)

    def __init__(self):
        super().__init__("snowy_monaro", "NSW", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> str:
        return _one_name(self._own_label(a, label))

    @staticmethod
    def _own_label(a: Tag, label: str) -> str:
        # "EXTRAORDINARY Council Meeting" (2024).
        label = re.sub(r"\bEXTRAORDINARY\b", "Extraordinary", label)
        # Only a paper's own link gets its meeting added: an "Items 14.3 and
        # 14.5" link under the same heading must stay nameless, or the
        # business-papers heading would make it an agenda.
        if _YEAR.search(label) or not _KIND.search(label):
            return label
        item = a.find_parent("li")
        if item:
            own = " ".join(
                s.strip() for s in item.children if isinstance(s, NavigableString)
            ).strip(" —-")
            if own:
                return f"{own} — {label}"
        heading = a.find_previous("h6")
        if heading:
            return f"{heading.get_text(' ', strip=True)} — {label}"
        return label
