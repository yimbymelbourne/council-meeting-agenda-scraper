import datetime
import re
from typing import Optional

from bs4 import Tag

from aus_council_scrapers import google_drive
from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.ionata import IonataMeetingsScraper
from aus_council_scrapers.scrapers.tas.ionata_year_check import IonataYearCheck
from aus_council_scrapers.sharepoint import file_share_download_url

# Huon Valley Council. An Ionata meetings archive: cards filtered server-side
# by `f_year` (2014 onwards), newest first, 14-18 cards a year on one page, so
# a production year is one request. The current year lists the rest of the
# year's meetings ahead of time, with no links until papers are up.
#
# A documented robots.txt exception. The papers are SharePoint share links,
# on huonvalleycouncil.sharepoint.com (team site `hvcwebsite`) and on
# huonvalleycouncil-my.sharepoint.com (council staff OneDrives). Both hosts'
# robots.txt is, in full (checked 26 Oct 2026):
#
#     User-Agent: *
#     Disallow: /
#
# The scraper itself requests only the listing on www.huonvalley.tas.gov.au,
# whose robots.txt disallows only /wp/wp-admin/ and sets no Crawl-delay. But
# council-alerts downloads every document URL a scraper emits, so emitting
# these links fetches the disallowed hosts. The maintainer decided on 26 Oct
# 2026 to do that anyway, because these papers are the council's official
# public record and its own page links each one for every visitor. The load
# is one download per paper. Nothing else on the SharePoint hosts is
# requested.
#
# Minutes first, because most agendas cannot be emitted. Every minutes link
# is a *file* share, which `aus_council_scrapers/sharepoint.py` turns into a
# download.aspx URL that returns the PDF itself. Most agendas are *folder*
# shares (the agenda beside its attachments), which open only with a guest
# cookie and have no URL a plain client can download; those are left out.
# Agendas linked as file shares (1-9 a year: 1 of 11 linked in 2026, 2 of 14
# in 2025, 9 of 14 in 2024, checked 26 Oct 2026) are emitted. So a meeting
# appears once its minutes are up, or earlier only when its agenda is a file
# share: most upcoming meetings are not emitted at all.
#
# Papers from January to August 2020, and March and April 2021 (13
# meetings), are on Google Drive: every minutes and one agenda as a file,
# the other agendas as a folder holding the agenda ("26 August 2020 - Agenda
# incl Reports WEBSITE.pdf"), its minutes, and "Attachments" and "Questions
# on Notice" sub-folders. A file is emitted as its `/uc?export=download`
# link, which returns the PDF without a login (`google_drive.py`; all 24
# emitted were checked on 26 Oct 2026, and each minutes' first page gives
# its card's date). A folder is read once, at
# drive.google.com/drive/folders/<id>, which robots.txt allows, and the one
# PDF in it named for the card's paper ("Agenda", not "Minutes") is emitted
# the same way; a folder without exactly one is left out and logged. That
# leaves the 15 July 2020 special meeting with its minutes only: its folder
# holds "15 July 2020 - Reports incl Cover WEBSITE.pdf", the reports with no
# order of business, and no agenda.
#
# The same robots.txt exception covers Drive, widened on 26 Oct 2026 by the
# maintainer's decision that council papers on robots-disallowed hosts all
# get it: drive.google.com/robots.txt ends `Disallow: /` after its allowed
# prefixes, so /uc is disallowed, and drive.usercontent.google.com, where /uc
# redirects, is `User-agent: *` / `Disallow: /` (both checked 26 Oct 2026).
# The scraper requests no /uc link itself; council-alerts downloads each one
# it emits. The folder pages cost one request each (9 for 2020, 2 for 2021)
# and only on a run for those years: no card since April 2021 links Drive,
# so a production run for the current year makes none.
#
# The card's header holds the date alone; its description holds the meeting
# type, the time and the place, "Ordinary Meeting | 6:00pm | Council
# Chambers". Before mid-2024 the time is a 12:00am placeholder and before 2022
# the type is blank, so the name falls back to the title ("December 2019
# Council Meeting – AGM", "March 2021 AGM (2019-2020)", "June 2019 Council
# Meeting – Special").
_LISTING_URL = (
    "https://www.huonvalley.tas.gov.au/council-governance/meetings-agendas-minutes/"
)

_PLACEHOLDER_TIME = re.compile(r"^12:00\s*am$", re.IGNORECASE)
_TIME = re.compile(r"^\d{1,2}(?::\d\d)?\s*[ap]m$", re.IGNORECASE)

_NAME_RULES = (
    (re.compile(r"annual general|\bagm\b", re.IGNORECASE), "Annual General Meeting"),
    (re.compile(r"\bspecial\b", re.IGNORECASE), "Special Meeting of Council"),
)


@register_scraper
class HuonValleyScraper(IonataYearCheck, IonataMeetingsScraper):
    listing_url = _LISTING_URL
    card_selector = "div.grid-item-alt"
    title_selector = ".grid-item-alt__title"
    date_selector = ".grid-item-alt__header"
    # The first year whose cards carry a paper that can be emitted (2020's
    # September-December minutes). Earlier years are not requested anyway.
    archive_starts = 2020

    def __init__(self):
        super().__init__("huon_valley", "TAS", "https://www.huonvalley.tas.gov.au")

    def document_url(self, href: str, kind: str) -> Optional[str]:
        # A SharePoint file share, or a Drive file or the card's paper in a
        # Drive folder, as its direct download. A SharePoint folder share or
        # anything else is not a document URL.
        if match := google_drive.FILE_ID.search(href):
            return google_drive.download_url(match.group(1))
        if match := google_drive.FOLDER_ID.search(href):
            return self._drive_folder_paper(match.group(1), kind)
        return file_share_download_url(href)

    def _drive_folder_paper(self, folder_id: str, kind: str) -> Optional[str]:
        files = google_drive.folder_files(self.fetcher, folder_id)
        if files is None:
            self.logger.warning(f"{self.council_name}: Drive folder {folder_id} is gone")
            return None
        other = "minutes" if kind == "agenda" else "agenda"
        named = [
            file_id
            for file_id, name in files
            if name.lower().endswith(".pdf")
            and kind in name.lower()
            and other not in name.lower()
            and "attach" not in name.lower()
        ]
        if len(named) != 1:
            self.logger.warning(
                f"{self.council_name}: Drive folder {folder_id} holds {len(named)} "
                f"PDFs named for its {kind}: {[name for _, name in files]}"
            )
            return None
        return google_drive.download_url(named[0])

    def meeting_name(self, card: Tag, title: str, documents: list[str]) -> str:
        meeting_type, _, _ = self._description(card)
        for pattern, name in _NAME_RULES:
            if pattern.search(meeting_type or "") or pattern.search(title):
                return name
        return "Ordinary Meeting of Council"

    @staticmethod
    def _description(card: Tag) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """The card's (type, time, location), each None when blank."""
        element = card.select_one(".grid-item-alt__description")
        if element is None:
            return None, None, None
        parts = [" ".join(p.split()) for p in element.get_text(" ").split("|")]
        meeting_type = parts[0] or None if parts else None
        time = location = None
        rest = parts[1:]
        if rest and _TIME.match(rest[0]):
            time = rest.pop(0)
            if _PLACEHOLDER_TIME.match(time):
                time = None
        if rest:
            location = " | ".join(rest) or None
        return meeting_type, time, location

    def _parse_card(
        self, card: Tag, year: int
    ) -> Optional[tuple[ScraperReturn, dict[str, datetime.date]]]:
        found = super()._parse_card(card, year)
        if found is None:
            return None
        record, disputed = found
        _, record.time, record.location = self._description(card)
        return record, disputed
