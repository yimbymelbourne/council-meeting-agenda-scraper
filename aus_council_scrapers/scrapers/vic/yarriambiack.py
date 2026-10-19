import re
from typing import Optional

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.yarriambiack.vic.gov.au"

# "15.1 Draft Financial Statements 2025-26", "11.2 Audit and Risk Committee
# Meeting Minutes – 10 August 2026": a report's attachment, numbered by the
# agenda item it belongs to.
_ITEM_NUMBER = re.compile(r"^\s*\d{1,2}\.\d{1,2}\b")
_ATTACHMENTS = re.compile(r"^\s*attachments?\s*:?\s*$", re.IGNORECASE)
# "Wednesday 24 June 2026 (Commencing at 3.00pm)".
_COMMENCING = re.compile(
    r"commencing\s+at\s+(\d{1,2}(?:[:.]\d{2})?\s*[ap]\.?m\.?)", re.IGNORECASE
)


@register_scraper
class YarriambiackScraper(OpenCitiesContentScraper):
    # One page, a rolling year of meetings (October 2025 onward when this
    # was written; older meetings are taken off the page and no archive is
    # linked from it or listed in the sitemap). A wysiwyg accordion panel per
    # meeting, headed by its date ("Wednesday 30 September 2026", "Wednesday
    # 12 November 2025 - Statutory Meeting"), holds the agenda and the
    # minutes, each titled with the date ("Council Meeting Agenda - 30
    # September 2026"), and then, under a bold "Attachments" line, a dozen
    # or more of the agenda's attachments numbered by item. Some of those are
    # other bodies' minutes ("11.2 Audit and Risk Committee Meeting Minutes –
    # 10 August 2026") and would read as meetings of their own, so nothing
    # after the "Attachments" line or numbered by item is a paper.
    #
    # Robots.txt disallows nothing under /Your-Council/Council-Meetings or
    # /files/, and sets no Crawl-delay. One request a night.
    pages = [ContentPage(f"{_BASE_URL}/Your-Council/Council-Meetings")]
    section_selector = "div.oc-wysiwyg-container-panel"
    heading_selector = "h2"

    def __init__(self):
        super().__init__("yarriambiack", "VIC", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> Optional[str]:
        if _ITEM_NUMBER.match(label):
            return None
        panel = a.find_parent("div", class_="oc-wysiwyg-container-panel")
        if panel is None:
            return label
        # Walk the panel in page order: an "Attachments" line before this
        # link means the link is one of them.
        for node in panel.descendants:
            if node is a:
                break
            if (
                isinstance(node, Tag)
                and node.name in ("p", "strong", "h3", "h4")
                and _ATTACHMENTS.match(node.get_text(" ", strip=True))
            ):
                return None
        # The start time, where the heading gives one that is not the usual.
        heading = panel.find("h2")
        m = _COMMENCING.search(heading.get_text(" ", strip=True)) if heading else None
        return f"{label} ({m.group(1)})" if m else label
