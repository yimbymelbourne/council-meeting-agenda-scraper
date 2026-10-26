import re
from typing import Optional
from urllib.parse import unquote, urlparse

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.temora.nsw.gov.au"
_MEETINGS = f"{_BASE_URL}/Your-Council/Council-Meetings"

# The words around a link's date that say nothing about the meeting: "Read
# the minutes from the February meeting", "View the agenda for the 15th
# October 2026 Ordinary Council Meeting.", "Action Minutes".
_FILLER = re.compile(
    r"\b(?:read|view|watch|the|minutes?|agenda|from|of|for|to|held|in|action"
    r"|meeting|council|ordinary|extra[\s-]*ordinary|special)\b|[.,]",
    re.IGNORECASE,
)


@register_scraper
class TemoraScraper(OpenCitiesContentScraper):
    # Minutes on a page per year ("Minutes-from-2026", back to 2018), found
    # from the Past Council Minutes page, under an h2 per month ("May
    # 2026"); and the latest agenda alone on the Business Papers page. No
    # older agenda is online, so past meetings have minutes only. The
    # links are sentences ("Read the 21st May Ordinary Meeting Minutes",
    # "Read the minutes from the February meeting"), read here as the
    # meeting type, the paper and whatever date they give. The day is in
    # the label or the filename ("action-minutes-19012023.pdf") until
    # 2023; since then most links and files give only the month, and those
    # meetings are left out rather than dated to the 1st.
    #
    # Robots.txt disallows nothing under /Your-Council/Council-Meetings or
    # /files/, and sets no Crawl-delay. Three requests a night.
    pages = [ContentPage(f"{_MEETINGS}/Business-Papers")]
    year_index = f"{_MEETINGS}/Past-Council-Minutes"
    year_page = re.compile(
        r"/Past-Council-Minutes/Minutes-from-(?P<year>\d{4})$", re.IGNORECASE
    )
    page_headings = ("h2",)
    # A year can hold minutes and no meeting with a day: 2024 had none, and
    # 2025 none before 16 October. Such a year raises rather than returning
    # nothing as if it were quiet.
    month_only_fails = True

    def __init__(self):
        super().__init__("temora", "NSW", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> Optional[str]:
        stem = unquote(urlparse(a.get("href", "")).path.rsplit("/", 1)[-1])
        words = f"{label} {stem.replace('-', ' ').replace('_', ' ')}"
        # "action-agenda-16072020.pdf", linked as "View the minutes from the
        # July 2020 meeting", is the agenda: its PDF opens "I hereby give
        # notice ... AGENDA Ordinary Council Meeting 16 July 2020". The
        # minutes are "...-action-minutes...".
        if re.search(r"\bagenda\b", label, re.IGNORECASE) or stem.lower().startswith(
            "action-agenda"
        ):
            paper = "Agenda"
        elif re.search(r"\bminutes?\b", label, re.IGNORECASE):
            paper = "Minutes"
        else:
            # "Planning Report January 2023".
            return None
        if re.search(r"\bextra[\s-]*ordinary\b", words, re.IGNORECASE):
            meeting = "Extraordinary Council Meeting"
        elif re.search(r"\bspecial\b", words, re.IGNORECASE):
            meeting = "Special Council Meeting"
        else:
            meeting = "Ordinary Council Meeting"
        when = re.sub(r"\s+", " ", _FILLER.sub(" ", label)).strip()
        return f"{meeting} - {paper} - {when}".rstrip(" -")
