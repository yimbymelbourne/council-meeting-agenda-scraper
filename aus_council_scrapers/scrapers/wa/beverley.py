import datetime
import re
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.councilconnect import _is_not_found
from aus_council_scrapers.councilconnect_filtered import (
    FilteredListingCouncilConnectScraper,
)

# A library item's label starts with the meeting's date: "20260225 February
# Ordinary Council Meeting Agenda". It is typed by hand and now and then
# wrong ("20240423 April ..." for the April 2025 agenda, "20242012" for 18
# December 2024), so an item is used only when that date is exactly a
# meeting's, and a wrong one simply matches nothing.
_LIBRARY_DATE = re.compile(r"^\s*(\d{4})(\d{2})(\d{2})\b")
# The minutes folder also holds the meeting recordings ("Recording Two of
# September Ordinary Council Meeting Minutes") and the electors' and audit
# committee minutes; the agenda folder an attachments bundle now and then.
_NOT_A_COUNCIL_PAPER = re.compile(
    r"recording|attach|elector|\bagm\b|audit|committee", re.IGNORECASE
)
_SPECIAL = re.compile(r"special", re.IGNORECASE)
# "Minuets" (28 August 2024) is the one misspelling in the folder.
_LIBRARY_KIND = {
    "agendas": re.compile(r"agenda", re.IGNORECASE),
    "minutes": re.compile(r"minu", re.IGNORECASE),
}
_UNCONFIRMED = re.compile(r"unconfir", re.IGNORECASE)


@register_scraper
class BeverleyScraper(FilteredListingCouncilConnectScraper):
    """Shire of Beverley—the meetings module, with gaps filled from the
    document library.

    Council meetings only, which leaves out the "Committee Meeting" type
    (audit and corporate committees) and the electors' meeting. Beverley has
    no per-type year pages—every /council-meetings/<type>/past/<year> is a
    404—which is why this reads the all-types listing. Headings are the date
    alone ("17 December 2025"), so every name is the type's. The module
    starts in 2021: /past/2020 is a 404.

    The module is the list of meetings, but it does not always carry their
    papers: the February to June 2026 Ordinary meetings have pages with no
    documents at all (checked 20 Oct 2026). The council also files every
    agenda and minutes in its document library, one folder a year
    (/documents/agendas-<year>, /documents/minutes-<year>), and each item
    there (/documents/<id>/<slug>) answers with the PDF itself. So where a
    meeting page lacks its agenda or minutes, the library's paper for that
    date and kind of meeting is used. A year's folders are read only once a
    meeting in it needs them: two requests, and in 2026 they are needed.

    The library goes back to 2020, a year earlier than the module. Its 2020
    papers have no meeting page to hang on and are not read here.

    The site is behind Cloudflare (server: cloudflare, cf-ray) and answered
    every request from a home IP without a challenge on 20 Oct 2026. It has
    not been tried from a GitHub runner.
    """

    # One production year: 13 requests, 24 s from a home connection
    # (20 Oct 2026), most of it the 2 s per-host delay.
    expected_seconds = 24
    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }
    first_year = 2021
    # Each was read on 20 Oct 2026. With these gone, /208 has no documents
    # and no library paper on its date, so it drops out; /180 takes its
    # minutes from the library.
    wrong_documents = {
        # Page 1 is the notice of the Ordinary meeting "on Tuesday 13
        # December 2022" (that meeting is /207, whose agenda comes from the
        # library). 13 October 2022 was a Thursday, and no meeting sat then:
        # the library holds no paper for it.
        "https://www.beverley.wa.gov.au/council-meetings/ordinary-council-meeting"
        "/13-october-2022/208/documents/13102022-agenda.pdf": (
            "the 13 December 2022 agenda, on a page for a meeting that did not sit"
        ),
        # Served as application/pdf, 46,499,647 bytes, but the body starts
        # c4 03 cf 7a, not %PDF, on each fetch. The library's copy
        # (/documents/2723/20250326-march-ordinary-council-meeting-minutes)
        # is a good PDF whose page 1 reads "26 March 2025 ORDINARY MEETING
        # MINUTES".
        "https://www.beverley.wa.gov.au/council-meetings/ordinary-council-meeting"
        "/26-march-2025/180/documents/26032025-minutes.pdf": (
            "not a PDF; the library's copy is"
        ),
    }

    def __init__(self):
        super().__init__("beverley", "WA", "https://www.beverley.wa.gov.au")
        self._library: dict[tuple[int, str], list[tuple[str, str]]] = {}

    def _library_items(self, year: int, kind: str) -> list[tuple[str, str]]:
        """(label, url) for every PDF in one year's agendas or minutes folder."""
        key = (year, kind)
        if key not in self._library:
            url = f"{self.base_url}/documents/{kind}-{year}"
            try:
                html = self.fetcher.fetch_with_requests(url)
            except requests.HTTPError as e:
                # A year's folder exists once its first paper is filed; the
                # upcoming page can name a meeting in a year that has none.
                # For any year already under way a 404 more likely means the
                # folder was renamed, and the meetings whose papers are only
                # here (February to June 2026) would drop out unseen, so it
                # is said out loud.
                if not _is_not_found(e):
                    raise
                if year > clock.current_year():
                    self.logger.info(f"No library folder yet: {url}")
                else:
                    self.logger.warning(
                        f"Library folder is a 404 for a year under way: {url}"
                    )
                html = ""
            items = []
            for link in BeautifulSoup(html, "html.parser").select(
                "table.dc-items-table a.doc-pdf[href]"
            ):
                # The label is followed by its upload date in a span.
                for span in link.select(".table-date"):
                    span.extract()
                items.append(
                    (link.get_text(" ", strip=True), urljoin(url, link["href"]))
                )
            self._library[key] = items
        return self._library[key]

    def _library_document(
        self, date: datetime.date, special: bool, kind: str
    ) -> Optional[str]:
        candidates = []
        for label, url in self._library_items(date.year, kind):
            match = _LIBRARY_DATE.match(label)
            if not match:
                continue
            try:
                named = datetime.date(*(int(part) for part in match.groups()))
            except ValueError:
                continue
            if (
                named == date
                and _LIBRARY_KIND[kind].search(label)
                and not _NOT_A_COUNCIL_PAPER.search(label)
                and bool(_SPECIAL.search(label)) == special
            ):
                candidates.append((label, url))
        # Confirmed minutes over unconfirmed, where both are up.
        candidates.sort(key=lambda c: bool(_UNCONFIRMED.search(c[0])))
        return candidates[0][1] if candidates else None

    def _meeting_from_detail(
        self, url, labels, fallback_when=None
    ) -> Optional[ScraperReturn]:
        meeting = super()._meeting_from_detail(url, labels, fallback_when)
        if meeting and meeting.agenda_url and meeting.minutes_url:
            return meeting
        # A page with no documents comes back as None, without its date;
        # the listing's (or the upcoming button's) date stands in.
        if meeting:
            date = parse_date(meeting.date).date()
        elif fallback_when and fallback_when[0]:
            date = fallback_when[0]
        else:
            return None

        type_slug = self.meeting_type_of(url)
        special = type_slug == "special-council-meeting"
        agenda_url = (meeting and meeting.agenda_url) or self._library_document(
            date, special, "agendas"
        )
        minutes_url = (meeting and meeting.minutes_url) or self._library_document(
            date, special, "minutes"
        )
        if not agenda_url and not minutes_url:
            return None
        if meeting is None:
            meeting = ScraperReturn(
                name=labels.get(type_slug) or self.meeting_types[type_slug],
                date=date.isoformat(),
                time=fallback_when[1],
                webpage_url=url,
            )
        meeting.agenda_url = agenda_url
        meeting.minutes_url = minutes_url
        meeting.download_url = agenda_url or minutes_url
        return meeting

    def scraper(self) -> list[ScraperReturn]:
        # The instance outlives a run (the registry holds it), and a folder
        # read on one run must not stand in for the next.
        self._library = {}
        return super().scraper()
