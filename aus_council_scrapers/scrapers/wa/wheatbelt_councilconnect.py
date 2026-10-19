"""Four CouncilConnect habits of the small Wheatbelt shires, handled in one place.

All four are gaps in `CouncilConnectScraper` that these councils hit and the
metropolitan ones do not. They belong in the base (`councilconnect.py`),
which is shared and not changed here; this class is where they live until
then, and moves into the base unchanged when it does.

**Month names in meeting headings.** The base strips a full date ("16
December 2025") from a heading, but these shires name meetings by month:
"October Ordinary Council Meeting held on 27 October 2026" (Dowerin),
"Ordinary Council Meeting September 2026" (Kulin), "Annual Elector's
Meeting - February 2026" (Williams), "April 2026 Ordinary Council Meeting"
(Bruce Rock). Left alone, the month and "held on" stay in the name and
the base's similarity test no longer recognises the meeting type, so
"October Ordinary Council Meeting held on" would be emitted as a name.

**Documents linked in the page body.** The base reads a meeting's papers
from its documents block, where every link is under
`<meeting page>/documents/`. From September 2026 Williams stopped using
that block: its meeting pages put the agenda, attachments and minutes
straight into the `meeting-info` body, under "Agenda", "Attachments" and
"Minutes" headings, as `/Profiles/<site>/Assets/ClientData/` files. The base
finds no documents there and drops the meeting, so a production run would
lose the newest meetings first. Some pages mix the two: Williams' 25
August 2026 Special meeting has its agenda and attachments in the block and
its confirmed minutes in the body. So the body's PDFs are always read
alongside the block's, under the headings they sit beneath, and the base's
rules—attachment groups skipped, minutes and agenda by group—apply
unchanged. ClientData paths are allowed by these sites'
robots.txt (only `Assets/ModuleData/` is disallowed) and carry no version,
so they are stable.

**Packet labels spelt with "&", "incl." or "w".** The base keeps "Agenda
and Attachments" as the agenda packet it is, but drops "Agenda &
Attachments" as an attachment; see `_PACKET_SPELLINGS`. At Dowerin that
was the agenda of nearly every meeting in 2020.

**Cancelled meetings.** A meeting page that carries a notice that the
meeting is cancelled is not emitted, even with an agenda beside it.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from requests.utils import requote_uri

from aus_council_scrapers.councilconnect import _HEADING_DATE, CouncilConnectScraper

_MONTH_NAME = (
    r"(?:january|february|march|april|may|june|july|august|september|october"
    r"|november|december)"
)
# A month with or without its year, a year on its own, and the "held on"
# a removed date leaves behind. Run after the base's full-date pattern, so
# "16 September 2026" has already gone whole.
_MONTH_NOISE = re.compile(
    rf"\b{_MONTH_NAME}\b(?:\s+\d{{4}})?|\b(?:19|20)\d{{2}}\b|\bheld\s+on\b",
    re.IGNORECASE,
)
# "Ordinary Council Meeting - April - Reconvened" leaves two dashes in a row.
_REPEATED_DASH = re.compile(r"(?:\s*[-–—]\s*){2,}")

# Packet labels in the forms the base's packet test does not know. Dowerin
# writes "Agenda & Attachments 18 August 2020" and "Minutes & Attachments",
# Victoria Plains "Public OCM Agenda incl. Attachments" (the full stop stops
# the base's "incl" from matching), and Corrigin "Council Minutes - 15
# October 2024 CONFIRMED w Attachments". Each is the meeting's only agenda
# or minutes, which the base would drop as an attachment. Each is rewritten
# to the "and"/"with"/"including" form the base already treats as a packet.
_PACKET_SPELLINGS = (
    (re.compile(r"\s*&\s*(?=attachments?\b)", re.IGNORECASE), " and "),
    (re.compile(r"\bincl\.\s*(?=attachments?\b)", re.IGNORECASE), "including "),
    (re.compile(r"\bw/?\s+(?=attachments?\b)", re.IGNORECASE), "with "),
)


# A notice that the meeting itself is off: Kulin's "Special Meeting
# CANCELLED", posted beside the agenda of a 12 September 2022 meeting that
# was never held.
_CANCELLED = re.compile(r"\bmeeting\s*[-–—:]?\s*cancel+ed\b", re.IGNORECASE)


def spell_packet(label: str) -> str:
    for pattern, replacement in _PACKET_SPELLINGS:
        label = pattern.sub(replacement, label)
    return label


class WheatbeltCouncilConnectScraper(CouncilConnectScraper):
    """CouncilConnect with the four habits above handled, and two
    per-council switches for what only reading a site can settle.

    `name_by_type`
        True where every meeting filed under the types in `meeting_types`
        is the meeting its type names, so the type's name is emitted and
        the hand-typed heading ("OCM", "Budget Adoption- Special Council
        Meeting") is not read for the name. Set only after reading every
        heading under those types.

    `corrected_dates`
        `{meeting page URL: "YYYY-MM-DD"}` for a meeting whose date field
        is plainly mistyped and the base's heading check cannot correct it
        (the heading names only a month, or the filenames do, so no document
        backs the heading), checked by reading the agenda. Like the base's
        `wrong_documents`, each entry is a document that was read.
    """

    name_by_type: bool = False
    corrected_dates: dict[str, str] = {}

    def _name(self, heading, type_slug, labels):
        if self.name_by_type and type_slug in (self.meeting_types or {}):
            return self.meeting_types[type_slug]
        cleaned = _HEADING_DATE.sub("", heading or "")
        cleaned = _MONTH_NOISE.sub("", cleaned)
        cleaned = _REPEATED_DASH.sub(" - ", cleaned)
        return super()._name(cleaned, type_slug, labels)

    def _meeting_from_detail(self, url, labels, fallback_when=None):
        meeting = super()._meeting_from_detail(url, labels, fallback_when)
        if meeting is not None and url in self.corrected_dates:
            meeting.date = self.corrected_dates[url]
        return meeting

    def _pick_documents(self, links):
        # A cancelled meeting has no record to keep, even where its agenda
        # went up before the cancellation.
        if any(_CANCELLED.search(label) for _, label, _ in links):
            return None, None
        return super()._pick_documents(
            [(group, spell_packet(label), url) for group, label, url in links]
        )

    def _detail_links(self, soup: BeautifulSoup, page_url: str):
        # The block's links and the body's together, never one as a fallback
        # for the other: a page can hold the agenda in one and the minutes in
        # the other (see the module docstring).
        links = super()._detail_links(soup, page_url)
        info = soup.find(class_="meeting-info")
        if info is None:
            return links
        seen = {url for _, _, url in links}
        group = ""
        for element in info.find_all(["h3", "a"]):
            if element.name == "h3":
                group = element.get_text(" ", strip=True)
                continue
            href = element.get("href")
            if not href:
                continue
            url = requote_uri(urljoin(page_url, href))
            if "/assets/clientdata/" not in urlparse(url).path.lower():
                continue
            if url in seen:
                continue
            seen.add(url)
            # The link text names the document ("Agenda - Council Meeting
            # 16th September 2026"), where the title is often just "Click
            # for more information". Now and then the text is the bare
            # path, and then the title is the better label.
            text = element.get_text(" ", strip=True)
            label = (
                text if text and not text.startswith("/") else element.get("title", "")
            )
            links.append((group, label, url))
        return links
