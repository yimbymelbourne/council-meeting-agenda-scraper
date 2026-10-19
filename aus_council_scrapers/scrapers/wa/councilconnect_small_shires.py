"""CouncilConnect, as the small WA shires fill it in.

Nine shires (Perenjori, Mukinbudin, Menzies, Wandering, Wyalkatchem, Tammin,
Trayning, Cue, Upper Gascoyne) run the same meetings module as Cottesloe, and
`CouncilConnectScraper` reads them. What it does not expect is how they type
into it. This class absorbs the habits they share, so each council's own
module only says what is particular to it:

- **Committees are skipped by heading and type, not by a list of types.**
  Each meeting costs a request, so committees are left out, as for Nedlands
  and Murray. But the base's way of doing that (`meeting_types`) reads one
  listing per type and misses any type it was not told about: Cue filed its
  21 April 2026 meeting under a one-off type named after the meeting,
  Perenjori its 2020 meetings under "Special Electronic Council Meeting", and
  Mukinbudin files its audit committee under "Special Council Meeting"
  anyway. So the all-types listing is read, and a meeting whose heading or
  type names a committee (or an audit or emergency-management meeting) is
  skipped before its page is fetched. Electors' meetings are kept: there is
  one a year, and the council must hold it.
- **Headings carry more than the meeting's name.** Mukinbudin numbers its
  meetings ("8. September 2026 Ordinary Meeting of Council"), Wandering and
  Upper Gascoyne put a bare month on either side ("September Ordinary Council
  Meeting"), and Cue doubles its spaces. The month, year and number are
  stripped before the base chooses a name.
- **"12:00 AM" is a blank, not a time.** Meetings entered before about 2021
  carry a midnight start, which is the module's default when no time was
  typed. It is dropped rather than emitted as a meeting time.
- **Small-hours times are PM typos.** Tammin's 22 April 2026 and 27 March
  2024 pages say 5:00 AM and Cue's 21 November 2023 page 6:00 AM, where the
  agendas say 5:00 pm and 6:00 PM. No shire meets before 8 am (the earliest
  real start across the nine is 8:00 AM), so a time from 1:00 to 6:59 AM is
  read as the same time PM.
- **Compact dates in filenames.** The base lets a heading's date beat the
  date field only when a document's filename names it, and it reads only
  "21 July 2022"-style dates. Wandering and Tammin name files "20220721..."
  and "30062021...", and their date fields are sometimes the upload date
  (Wandering's 21 July 2022 meeting has 15 July in the field). Those forms
  are read too, so the heading wins on the same evidence the base requires.
- **Labels the base misreads.** Perenjori's only agenda is "Agenda &
  Attachments", which the packet test (`and attachments`) missed, so the
  agenda was dropped as an attachment. Tammin's 2020 labels start with a
  dotted date ("22.12.2020 Special Council Meeting Agenda"), which the base
  takes for an item number ("12.1 Attachment"). Wandering writes "with non
  confidential attachments".
- **Other bodies' papers.** Councils receive the minutes of committees and
  regional groups as attachments, and some file them beside the meeting's own
  ("Bush Fire Advisory Committee General Meeting Minutes" under Wandering's
  "Documents"). Minutes whose label names a committee or working group are
  never the council meeting's minutes.
- **An agenda filed in the wrong group.** Cue and Mukinbudin have put a
  meeting's agenda under "Attachments", and Tammin's "26.06.2024 Ordinary
  Council Meeting Agenda" has "includes-late-item" in its filename. Where the
  base finds no agenda, a single document labelled with nothing but a meeting
  name and "Agenda" is taken as it.
- **Documents in the meeting description.** Wyalkatchem's meetings before
  2025 have no documents block; their PDFs are linked from the description
  text inside `.meeting-info`, under "Agenda" and "Minutes" headings, and live
  under `/Assets/ClientData/`. Those are read when the block is missing.
- **One meeting, two pages.** Perenjori's 22 April 2021 Special meeting and
  Wyalkatchem's 16 December 2021 meeting each have two pages. Meetings with
  the same date and name are merged, the first page's documents first.

`corrected_dates` holds a meeting whose page gives the wrong date, checked by
reading its documents, in the spirit of the base's `wrong_documents`.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import replace
from typing import Optional
from urllib.parse import urljoin, urlparse

from requests.utils import requote_uri

from aus_council_scrapers.base import ScraperReturn
from aus_council_scrapers.councilconnect import (
    _HEADING_DATE,
    _NOT_THE_MEETINGS,
    _PACKET,
    CouncilConnectScraper,
)

# Bodies that are not the council meeting itself. Wider than the base's
# `_NOT_A_COUNCIL_MEETING`: the shires misspell committee ("Audit Comittee",
# "Audit Commitee Meeting"), and some headings are only an acronym ("LEMC")
# or "Audit Meeting".
_NOT_A_COUNCIL_MEETING = re.compile(
    r"forum|briefing|\bcomm?it+e+s?\b|working\s+group|advisory\s+group"
    r"|\baudit\b|\blemc?\b|emergency\s+management",
    re.IGNORECASE,
)
# Another body's papers, by their label.
_OTHER_BODY = re.compile(
    r"\bcomm?it+e+s?\b|working\s+group|advisory\s+group", re.IGNORECASE
)

# What is left of a date once the base's day-month pattern has had its turn:
# a bare month, a month and year, a year, or a financial year ("2020-2021").
# Months are spelled out or cut to three letters, never a prefix, so that
# "Mayoral" is not taken for May.
_MONTH_WORD = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_LEFTOVER_DATE = re.compile(
    rf"\b{_MONTH_WORD}\b(?:\s+\d{{4}})?"
    r"|\b(?:19|20)\d{2}(?:\s*[-/]\s*(?:19|20)?\d{2})?\b",
    re.IGNORECASE,
)
# Mukinbudin's meeting number: "8. September 2026 ...".
_MEETING_NUMBER = re.compile(r"^\s*\d{1,2}\.\s+")
# A label that starts with a dotted date, "22.12.2020 Special ...". The year
# has four digits, which no item number ("9.2.1", "12.1") does.
# No `\b` after the year: Tammin's "25.03.2021Ordinary Council Meeting" has
# no space there, and a word boundary between two word characters fails.
_DOTTED_DATE = re.compile(r"^\s*\d{1,2}\.\d{1,2}\.(?:19|20)\d{2}(?!\d)\s*")
# Filename dates: "20220721-agenda", "30062021-special-council-meeting".
_YMD = re.compile(r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)")
_DMY = re.compile(r"(?<!\d)(\d{2})(\d{2})((?:19|20)\d{2})(?!\d)")
# Wandering: "SCM Agenda 14 Jan 2025 - with non confidential attachments".
_NON_CONFIDENTIAL = re.compile(r"\bnon[\s-]+confidential\s+(?=attach)", re.IGNORECASE)
# A label that is a meeting's agenda and nothing else, once dates are gone:
# "Ordinary Council Meeting Agenda", "Agenda Special Council Meeting".
_ONLY_AN_AGENDA = re.compile(
    r"(?:[\w']+\s+){0,4}agenda(?:\s+[\w']+){0,4}", re.IGNORECASE
)
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
_MINUTES = re.compile(r"minut", re.IGNORECASE)

_MIDNIGHT = "12:00 AM"
# "5:00 AM": a start in the small hours, which no shire holds.
_SMALL_HOURS = re.compile(r"^([1-6]):(\d{2}) AM$")


def _clean_time(time: Optional[str]) -> Optional[str]:
    """A meeting time with the module's blanks and AM/PM typos taken out."""
    if time == _MIDNIGHT:
        return None
    match = _SMALL_HOURS.match(time or "")
    if match:
        return f"{match.group(1)}:{match.group(2)} PM"
    return time


class SmallShireCouncilConnectScraper(CouncilConnectScraper):
    """`CouncilConnectScraper` for the small shires; see the module docstring.

    `type_names`
        `{type-slug: "Display Name"}` for a type whose own label is too bare to
        name a meeting (Wyalkatchem's "Ordinary", "Special"). A meeting of
        that type takes the name whatever its heading says.
    `corrected_dates`
        `{meeting page url: (iso date, time or None, why)}` for a meeting
        whose page gives the wrong date, checked by reading its documents.
    """

    type_names: dict[str, str] = {}
    corrected_dates: dict[str, tuple[str, Optional[str], str]] = {}

    # --- what to read ---------------------------------------------------------

    def _summary_meeting(self, summary, listing_url, labels, year, seen):
        heading = summary.find(["h2", "h3"])
        text = heading.get_text(" ", strip=True) if heading else ""
        # Tammin heads some audit committee meetings with the date alone
        # ("13 December 2021"); only the type in the link says what they are.
        types = " ".join(
            (self.meeting_type_of(urljoin(listing_url, a["href"])) or "").replace(
                "-", " "
            )
            for a in summary.find_all("a", href=True)
        )
        if _NOT_A_COUNCIL_MEETING.search(f"{text} {types}"):
            return []
        return super()._summary_meeting(summary, listing_url, labels, year, seen)

    def scraper(self) -> list[ScraperReturn]:
        # Upcoming meetings are linked by date, not heading, so a committee
        # among them is only known once its page has been read.
        meetings = [
            meeting
            for meeting in super().scraper()
            if not _NOT_A_COUNCIL_MEETING.search(meeting.name or "")
        ]
        # The base raises when it found nothing, but that check runs before
        # this filter. A year whose only meetings with papers were committees
        # would otherwise return [], which reads as a successful scrape.
        if not meetings:
            raise RuntimeError(
                f"{self.council_name}: no council meetings with documents for "
                f"{sorted(self._wanted_years())}; only committees were found"
            )
        return self._merge_duplicates(meetings)

    def _merge_duplicates(self, meetings: list[ScraperReturn]) -> list[ScraperReturn]:
        """One record per date and name, documents filled from later copies.

        Two meetings of one name on one day are kept apart only where both
        give a time and the times differ.
        """
        merged: list[ScraperReturn] = []
        for meeting in meetings:
            twin = next(
                (
                    i
                    for i, kept in enumerate(merged)
                    if kept.date == meeting.date
                    and kept.name == meeting.name
                    and (not kept.time or not meeting.time or kept.time == meeting.time)
                ),
                None,
            )
            if twin is None:
                merged.append(meeting)
                continue
            kept = merged[twin]
            self.logger.info(
                f"{meeting.webpage_url} is the same meeting as {kept.webpage_url}"
            )
            agenda_url = kept.agenda_url or meeting.agenda_url
            minutes_url = kept.minutes_url or meeting.minutes_url
            merged[twin] = replace(
                kept,
                time=kept.time or meeting.time,
                agenda_url=agenda_url,
                minutes_url=minutes_url,
                download_url=agenda_url or minutes_url,
                location=kept.location or meeting.location,
                _cleaned_time=None,
            )
        return merged

    # --- names, dates and times ---------------------------------------------

    def _type_labels(self, soup) -> dict[str, str]:
        labels = {
            slug: re.sub(r"\s+", " ", name).strip()
            for slug, name in super()._type_labels(soup).items()
        }
        labels.update(self.type_names)
        return labels

    def _name(self, heading: str, type_slug: Optional[str], labels: dict) -> str:
        if type_slug in self.type_names:
            return self.type_names[type_slug]
        # The base's own first step, taken here so that the date inside
        # "(rescheduled from 1 May 2020)" is not stripped before the
        # parenthesis it belongs to.
        cleaned = re.sub(r"\([^)]*\d{4}[^)]*\)", "", heading or "")
        cleaned = _MEETING_NUMBER.sub("", cleaned)
        cleaned = _HEADING_DATE.sub("", cleaned)
        cleaned = _LEFTOVER_DATE.sub("", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—,:")
        return re.sub(r"\s+", " ", super()._name(cleaned, type_slug, labels))

    @staticmethod
    def _parse_when(text: str) -> tuple[Optional[datetime.date], Optional[str]]:
        date, time = CouncilConnectScraper._parse_when(text)
        return date, _clean_time(time)

    @staticmethod
    def _names_date(text: str, date: datetime.date) -> bool:
        if CouncilConnectScraper._names_date(text, date):
            return True
        named = [(int(y), int(m), int(d)) for y, m, d in _YMD.findall(text)]
        named += [(int(y), int(m), int(d)) for d, m, y in _DMY.findall(text)]
        return (date.year, date.month, date.day) in named

    def _meeting_from_detail(self, url, labels, fallback_when=None):
        meeting = super()._meeting_from_detail(url, labels, fallback_when)
        if meeting is None:
            return None
        # The listing and page times go through _parse_when, but an upcoming
        # meeting's time comes from its button.
        if meeting.time != _clean_time(meeting.time):
            meeting = replace(
                meeting, time=_clean_time(meeting.time), _cleaned_time=None
            )
        correction = self.corrected_dates.get(meeting.webpage_url)
        if correction:
            date, time, why = correction
            self.logger.info(f"{url}: date corrected to {date} ({why})")
            meeting = replace(
                meeting, date=date, time=time, _cleaned_date=None, _cleaned_time=None
            )
        return meeting

    # --- documents -----------------------------------------------------------

    @staticmethod
    def _tidy_label(label: str) -> str:
        label = _DOTTED_DATE.sub("", label or "")
        label = _NON_CONFIDENTIAL.sub("", label)
        return re.sub(r"\s*&\s*", " and ", label)

    def _pick_documents(self, links):
        # Minutes only: an agenda labelled for a committee has turned out to
        # be a typo for the council meeting's own ("Ordinary Committee
        # Meeting Agenda 22 May 2024", Tammin).
        links = [
            (group, self._tidy_label(label), url)
            for group, label, url in links
            if not (_OTHER_BODY.search(label or "") and _MINUTES.search(label or ""))
        ]
        agenda_url, minutes_url = super()._pick_documents(links)
        if agenda_url is None:
            agenda_url = self._lone_agenda(links)
        return agenda_url, minutes_url

    def _lone_agenda(self, links) -> Optional[str]:
        """The one PDF labelled as a meeting's agenda and nothing more."""
        candidates = []
        for _, label, url in links:
            if url in self.wrong_documents:
                continue
            if not urlparse(url).path.lower().endswith(".pdf"):
                continue
            if _MINUTES.search(label) or _NOT_THE_MEETINGS.search(
                _PACKET.sub("", label)
            ):
                continue
            bare = _LEFTOVER_DATE.sub("", _HEADING_DATE.sub("", label))
            bare = re.sub(r"[^\w']+", " ", bare).strip()
            if _ONLY_AN_AGENDA.fullmatch(bare):
                candidates.append(url)
        return candidates[0] if len(candidates) == 1 else None

    def _detail_links(self, soup, page_url: str):
        links = super()._detail_links(soup, page_url)
        if links:
            return links
        # The older form: PDFs linked from the description, grouped by h3s.
        # Only `.meeting-info` is read, which holds nothing but this meeting;
        # the site-wide document menu is outside it.
        info = soup.find(class_="meeting-info")
        if info is None:
            return []
        host = urlparse(page_url).netloc
        group = ""
        for element in info.find_all(["h3", "a"]):
            if element.name == "h3":
                group = element.get_text(" ", strip=True)
                continue
            href = element.get("href")
            if not href:
                continue
            url = requote_uri(urljoin(page_url, href))
            parsed = urlparse(url)
            if parsed.netloc != host or not parsed.path.lower().endswith(".pdf"):
                continue
            # The text, not the title: Wyalkatchem titles its minutes links
            # "Click for more information".
            label = element.get_text(" ", strip=True) or element.get("title") or ""
            links.append((group, label, url))
        return links
