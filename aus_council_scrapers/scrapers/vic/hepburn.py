import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import NavigableString, Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.hepburn.vic.gov.au"

# "Time: 6:00 pm", "Time - 7:00pm".
_TIME_LINE = re.compile(r"^\s*time\s*[:\-–]\s*(.+)$", re.IGNORECASE)

# Panels the PDF contradicts, by filename: the heading and start time the
# PDF gives. The heading names the meeting, so a wrong one makes a meeting
# of the wrong type.
_PANEL_IS_WRONG = {
    # Headed "14 January 2020 - Ordinary Meeting of Council", "Time -
    # 6.00pm"; the minutes read "Special Meeting of Council ... Tuesday 14
    # January 2020 9:00AM".
    "minutes-special-meeting-14-january-2020.pdf": (
        "14 January 2020 - Special Meeting of Council",
        "9:00 am",
    ),
    # "Time - 5.30pm"; the minutes: "Commencing at 5:15 PM".
    "confirmed-public-minutes-confidential-meeting-of-council-29-august-2022.pdf": (
        "29 August 2022 - Confidential Meeting of Council",
        "5:15 pm",
    ),
}


@register_scraper
class HepburnScraper(OpenCitiesContentScraper):
    # One page, every meeting from 2018: a wysiwyg accordion panel per
    # meeting, headed by its date and type ("22 September 2026 - Ordinary
    # Meeting of Council"), with one paragraph per paper: "Agenda - View
    # Agenda", "Attachments - View Attachments", "Minutes - View Minutes".
    # The link text says only "View Agenda", so the paragraph's own words
    # say what the paper is and the heading says which meeting it is for.
    # Agendas run only from late 2023; earlier meetings have minutes alone.
    #
    # Robots.txt disallows nothing under /Council/Council-meetings or
    # /files/, and sets no Crawl-delay. One request a night.
    pages = [ContentPage(f"{_BASE_URL}/Council/Council-meetings/Agendas-and-minutes")]
    section_selector = "div.oc-wysiwyg-container-panel"
    heading_selector = "h2, h3"
    # "29 August 2022 - Confidential Meeting of Council" is a meeting held
    # in closed session whose public minutes are on the page; the PDF is
    # headed "Confidential Meeting of Council ... Public Minutes".
    meeting_words = re.compile(r"\bconfidential\s+meeting\b", re.IGNORECASE)

    def __init__(self):
        super().__init__("hepburn", "VIC", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> Optional[str]:
        panel = a.find_parent("div", class_="oc-wysiwyg-container-panel")
        paragraph = a.find_parent("p")
        if panel is None or paragraph is None:
            return None
        # What the paragraph calls the paper, before its link: "Agenda",
        # "Draft minutes", "Minutes Attachments". A paragraph with no such
        # word ahead of the link ("Statement by the Mayor ...") is no paper
        # of the meeting.
        # Stop at the first link, not this one: the second of "Minutes - Part
        # one Part two" is still a paper of the "Minutes" paragraph.
        lead = []
        for node in paragraph.children:
            if isinstance(node, Tag) and (node.name == "a" or node.find("a")):
                break
            if isinstance(node, NavigableString):
                lead.append(str(node))
            else:
                lead.append(node.get_text(" "))
        # "Draft minutes: View" puts the link's first word outside it.
        kind = re.sub(r"\s+", " ", "".join(lead)).strip(" :-–")
        kind = re.sub(r"[\s:–-]*\bview$", "", kind, flags=re.IGNORECASE)
        if not kind:
            return None
        filename = urlparse(a.get("href", "")).path.rsplit("/", 1)[-1]
        heading, time = _PANEL_IS_WRONG.get(filename, (None, None))
        if heading is None:
            found = panel.find(["h2", "h3"])
            heading = found.get_text(" ", strip=True) if found else ""
            time = self._time(panel)
        # "Special Council Meeting" (September 2024) and "Ordinary Council
        # Meeting" (March 2024) are the council's other spelling of the
        # meeting types every other panel calls "... Meeting of Council".
        heading = re.sub(
            r"\b(Ordinary|Special|Statutory)\s+Council\s+Meeting\b",
            r"\1 Meeting of Council",
            heading,
        )
        parts = [heading, kind]
        # The December 2021 minutes are in two links, "Part one" and "Part
        # two"; the part number keeps part one as the minutes.
        if re.search(r"\bpart\b", label, re.IGNORECASE):
            parts.append(label)
        text = " - ".join(parts)
        return f"{text} ({time})" if time else text

    @staticmethod
    def _time(panel: Tag) -> Optional[str]:
        for line in panel.select(".oc-wysiwyg-container-panel-content > p"):
            m = _TIME_LINE.match(line.get_text(" ", strip=True))
            if m:
                return m.group(1).strip()
        return None
