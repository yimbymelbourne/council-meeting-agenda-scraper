import datetime
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
    # 2023; since then most links and files give only the month.
    #
    # Each such minutes file opens with the day ("Date: Thursday, 19
    # February 2026 Time: 4:00pm ... MINUTES Ordinary Council Meeting"), but
    # it is the whole business paper with its attachments, 5 to 210 MB, and
    # the server ignores Range requests and sends no length, so the first
    # page cannot be read without downloading the file. Reading 2026's eight
    # every night would cost about 360 MB, so `pdf_dates` is not used.
    # Instead the day each month-only minutes gives on its first page was
    # read once (26 Oct 2026) and is listed in `misfiled`. A month-only
    # paper published since is left out, logged, until it is added there.
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

    # Minutes labelled by month only, dated from their first page ("Date:
    # Thursday, 19 February 2026 ... MINUTES Ordinary Council Meeting 19
    # February 2026"), read once on 26 Oct 2026. Every one was a Thursday
    # but the 9 June 2026 extraordinary meeting, a Tuesday.
    misfiled = {
        "action-minutes-january-2020.pdf": datetime.date(2020, 1, 16),
        "february-2020-action-minutes.pdf": datetime.date(2020, 2, 20),
        "october-2020-action-minutes.pdf": datetime.date(2020, 10, 15),
        "november-2020-action-minutes.pdf": datetime.date(2020, 11, 19),
        "march-2021-action-minutes.pdf": datetime.date(2021, 3, 18),
        "november-2021-action-minutes.pdf": datetime.date(2021, 11, 18),
        "july-2022-action-minutes.pdf": datetime.date(2022, 7, 21),
        "august-2022-action-minutes.pdf": datetime.date(2022, 8, 18),
        "december-2022-action-minutes.pdf": datetime.date(2022, 12, 15),
        "february-2023-action-minutes.pdf": datetime.date(2023, 2, 16),
        "may-2023-action-minutes.pdf": datetime.date(2023, 5, 18),
        "july-2023-action-minutes.pdf": datetime.date(2023, 7, 20),
        "august-2023-action-minutes.pdf": datetime.date(2023, 8, 17),
        "september-2023-action-minutes.pdf": datetime.date(2023, 9, 21),
        "october-2023-action-minutes.pdf": datetime.date(2023, 10, 19),
        "november-2023-action-minutes.pdf": datetime.date(2023, 11, 30),
        "december-2023-action-minutes.pdf": datetime.date(2023, 12, 21),
        "january-2024-action-minutes.pdf": datetime.date(2024, 1, 18),
        "february-2024-action-minutes.pdf": datetime.date(2024, 2, 15),
        "march-2024-action-minutes.pdf": datetime.date(2024, 3, 21),
        "april-2024-action-minutes.pdf": datetime.date(2024, 4, 18),
        "may-2024-action-minutes.pdf": datetime.date(2024, 5, 16),
        "june-2024-action-minutes.pdf": datetime.date(2024, 6, 20),
        "july-2024-action-minutes.pdf": datetime.date(2024, 7, 18),
        "august-2024-action-minutes.pdf": datetime.date(2024, 8, 15),
        "november-2024-action-minutes.pdf": datetime.date(2024, 11, 28),
        "december-2024-action-minutes.pdf": datetime.date(2024, 12, 19),
        "january-2025-action-minutes.pdf": datetime.date(2025, 1, 16),
        "february-2025-action-minutes.pdf": datetime.date(2025, 2, 20),
        "march-2025-action-minutes.pdf": datetime.date(2025, 3, 20),
        "april-2025-action-minutes.pdf": datetime.date(2025, 4, 17),
        # Linked only as "Read the minutes" under a month heading, which the
        # base does not date a paper from.
        "may-2025-action-minutes.pdf": datetime.date(2025, 5, 15),
        "june-2025-action-minutes.pdf": datetime.date(2025, 6, 19),
        "july-2025-action-minutes.pdf": datetime.date(2025, 7, 17),
        "august-2025-action-minutes.pdf": datetime.date(2025, 8, 21),
        "september-2025-action-minutes.pdf": datetime.date(2025, 9, 18),
        "november-2025-action-minutes.pdf": datetime.date(2025, 11, 20),
        "december-2025-action-minutes.pdf": datetime.date(2025, 12, 18),
        "february-2026-action-minutes.pdf": datetime.date(2026, 2, 19),
        "march-2026-action-minutes.pdf": datetime.date(2026, 3, 19),
        "april-2026-action-minutes.pdf": datetime.date(2026, 4, 16),
        "june-2026-extraordinary-council-minutes.pdf": datetime.date(2026, 6, 9),
        "june-2026-action-minutes.pdf": datetime.date(2026, 6, 18),
        "july-2026-action-minutes.pdf": datetime.date(2026, 7, 16),
        "august-2026-action-minutes.pdf": datetime.date(2026, 8, 20),
        "september-2026-action-minutes.pdf": datetime.date(2026, 9, 17),
    }

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
