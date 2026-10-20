import re
import urllib.parse

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.craft import CraftMeeting
from aus_council_scrapers.scrapers.vic.craft_agendas_minutes import (
    CraftAgendasMinutesTableScraper,
)

# Bass Coast Shire Council. A SimpleGov Craft archive; the row parser is
# shared with Mitchell (see `craft_agendas_minutes.py`) and the fetch-and-page
# loop with the SA Craft councils (`aus_council_scrapers/craft.py`). About 23
# rows a page: 2020 to date is five pages, one year one.
#
# The unfiltered listing shows Council meetings only. The committee filter
# offers external bodies too (the MAV, the Peri Urban group), which publish
# nothing here. Agendas are labelled "Agenda With Attachments" and are the
# whole business paper; the attachments folder holds late notes and single
# items, and is not read.
#
# The same AWS WAF as Mitchell: 202 and an empty body to the identifying
# User-Agent, the page to BROWSER_USER_AGENT from home, unmeasured from a
# GitHub runner, so the listing is loaded in Chrome.

# Every row's Committee cell says "Council Meeting", special meetings and the
# 2022 delegated committee included, so on 15 April and 19 August 2020 two
# rows share a date and a name: the ordinary meeting and a special meeting
# for the cemetery trusts. The papers' filenames say which is which
# ("Special-Council-Meeting-Agenda-inc-Attachments-Cemetery-Trusts-15-April-
# 2020.pdf", "Open-Delegated-Committee-Meeting-Agenda-24-November-2022.pdf"),
# so the name is read from them. The same goes for the 22 April 2026 closed
# meeting (Website-Version-Closed_Council_Meeting_-_22-April-2026.pdf), whose
# paper opens "Closed Council Meeting Agenda": named "Council Meeting" it
# would read as an ordinary meeting a week before the real one.
_NAME_RULES = (
    (
        re.compile(r"delegated[\s_-]+committee", re.IGNORECASE),
        "Delegated Committee Meeting",
    ),
    (
        re.compile(r"(?<![a-z])special(?![a-z])", re.IGNORECASE),
        "Special Council Meeting",
    ),
    (
        re.compile(r"(?<![a-z])closed(?![a-z])", re.IGNORECASE),
        "Closed Council Meeting",
    ),
)
_PAPER_FOLDER = re.compile(r"/(?:agendas|minutes)/", re.IGNORECASE)


@register_scraper
class BassCoastScraper(CraftAgendasMinutesTableScraper):
    listing_url = (
        "https://www.basscoast.vic.gov.au/about-council/"
        "council-meetings-information/council-meetings"
    )

    def __init__(self):
        super().__init__("bass_coast", "VIC", "https://www.basscoast.vic.gov.au")

    def parse_meetings(self, soup: BeautifulSoup) -> list[CraftMeeting]:
        meetings = super().parse_meetings(soup)
        for meeting in meetings:
            filenames = " ".join(
                urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
                for _, url in meeting.links
                if _PAPER_FOLDER.search(urllib.parse.urlsplit(url).path)
            )
            for pattern, name in _NAME_RULES:
                if pattern.search(filenames):
                    meeting.name = name
                    break
        return meetings
