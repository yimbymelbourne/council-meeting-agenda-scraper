import re
from typing import Optional

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import OpenCitiesContentScraper

_BASE_URL = "https://www.loddon.vic.gov.au"
_INDEX = f"{_BASE_URL}/Our-Council/Agendas-and-minutes"

_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)


@register_scraper
class LoddonScraper(OpenCitiesContentScraper):
    # A page per year from 2012 ("Agendas-and-minutes-2026"), all linked
    # from the Agendas and minutes page. Each year page has a wysiwyg
    # accordion panel per meeting, headed by its date and type ("29
    # September 2026 Council Meeting", "11 November 2025 Special Council
    # Meeting"), holding the agenda and the minutes, each titled with the
    # date again ("29 September 2026 Council Meeting Minutes
    # (Unconfirmed)"). The 2020 page also files a late report beside the
    # agenda, which the base leaves out. Labels before 2013 give only the
    # month; EARLIEST_YEAR keeps those pages out of range.
    #
    # Production asks for one year: the index and that year's page, two
    # requests. Robots.txt disallows nothing under /Our-Council/Agendas-and-
    # minutes or /files/, and sets no Crawl-delay.
    year_index = _INDEX
    year_page = re.compile(
        r"/Our-Council/Agendas-and-minutes/Agendas-and-minutes-(?P<year>\d{4})$"
    )
    section_selector = "div.oc-wysiwyg-container-panel"
    heading_selector = "h2"

    def __init__(self):
        super().__init__("loddon", "VIC", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> Optional[str]:
        # One name per meeting type. The ordinary meeting is "Council
        # Meeting" in every year but 2020, whose labels and headings say
        # "Ordinary Meeting", and 2020's special meeting is a "Special
        # Meeting" where every later one is a "Special Council Meeting".
        label = re.sub(r"\bOrdinary Meeting\b", "Council Meeting", label)
        label = re.sub(r"\bSpecial Meeting\b", "Special Council Meeting", label)
        # The 14 November 2023 papers are titled "14 November 2023 Council
        # Meeting Agenda" under the heading "14 November 2023 Special Council
        # Meeting", and their files end "_extra", the council's name for a
        # special meeting's papers. The heading names the meeting.
        panel = a.find_parent("div", class_="oc-wysiwyg-container-panel")
        heading = panel.find("h2") if panel else None
        if (
            heading
            and _SPECIAL.search(heading.get_text(" ", strip=True))
            and not _SPECIAL.search(label)
        ):
            label = re.sub(r"\bCouncil Meeting\b", "Special Council Meeting", label)
        return label
