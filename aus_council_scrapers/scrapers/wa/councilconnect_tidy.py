"""Tidy-ups some small WA CouncilConnect councils need on top of the base.

None belongs in `CouncilConnectScraper` itself yet: each has been checked
only against the councils that use it, and switching one on for the
councils recorded before it existed would rewrite their fixtures.

Naming by type (`name_by_type = True`)
    The base names a meeting from its hand-typed heading unless the heading
    is close enough to the type's name. Some councils' headings carry more
    than the meeting's name—the month ("December Ordinary Council
    Meeting", "Council Meeting - February 2021"), the hour ("Ordinary
    Meeting of Council 25 March 2025 - 5.00pm"), the business ("Special
    Meeting of Council - Budget Adoption") or the venue ("Ordinary Meeting
    of Council (Coral Bay)")—and those come through as names. For a council
    read through `meeting_types`, the type a meeting is filed under is its
    name, with exceptions that the heading settles. An electors' meeting
    filed under a Council type keeps the base's name for it (Donnybrook-
    Balingup filed its 2020 and 2021 electors' meetings under Special,
    headed "2021 Annual General Meeting of Electors", so the year is taken
    off). A heading that says "Special" is a Special meeting whatever it is
    filed under (Plantagenet filed its 7 July 2020 Special budget meeting
    under Ordinary), and one that says "Ordinary" is an Ordinary meeting
    (Denmark filed its 21 April 2020 Ordinary meeting under Special).

Briefing papers are never the agenda
    Councils file the papers for the councillors' briefing a week before a
    meeting under that meeting's "Agenda" heading: "ABS Agenda - 21 October
    2026" (an agenda briefing session, Donnybrook-Balingup), "16 Oct 2024
    Agenda Briefing Agenda" (Toodyay), "Draft OCM Agenda for Q&A"
    (Bridgetown-Greenbushes). A briefing decides nothing. Where it is the
    only paper up, as it is at Donnybrook-Balingup until the real agenda is
    posted, the base would emit it as the meeting's agenda; it is dropped
    first, on its label or its filename.

Midnight is not a meeting time
    Carnarvon's meetings up to April 2022 have "12:00 AM" in the date field,
    which is the module's empty time, not an hour anyone met at.

An hour before a council ever meets is a typo
    The date field's AM/PM is picked by hand, and now and then the wrong
    one is. Donnybrook-Balingup's 23 June 2021 Ordinary meeting reads "5:00
    AM" (the minutes say "Commencing at 5.00pm") and its 29 September 2021
    electors' meeting "7:00 AM" (opened at 6:00pm);
    Bridgetown-Greenbushes' 27 May 2021 Ordinary meeting reads "5:30 AM"
    (opened at 5.30pm). A council that sets `earliest_hour` has its AM
    times before that hour emptied. They are not flipped to PM, because
    the electors' meeting shows the typo is not always only the AM/PM.
    There is no default: Katanning held a Special meeting at 7:30am on 3
    October 2025 (the minutes say it opened at 7:34am).

Merging a meeting entered twice
    Now and then a council enters one meeting in the module twice, as two
    pages. Toodyay put the 8 March 2021 Special meeting's agenda on one page
    and its minutes on another (the minutes' business matches the agenda's,
    item for item); Katanning has the 22 May 2024 Ordinary meeting on two
    pages carrying the same files; Bridgetown-Greenbushes has 29 February
    2024 on two pages, one with the agenda and confirmed minutes, the other
    with a second copy of the minutes alone. Complementary rows are merged
    by `_merge_split_meetings`, as InfoCouncil's are. Rows that share a name,
    a date and a start time are also one meeting—a council cannot hold two
    Ordinary meetings at the same hour—so they merge too, the one with more
    papers kept and gaps filled from the other. Rows without a time
    (Toodyay gives none) merge only when complementary: Toodyay held two
    Special meetings on 9 August 2021, at 2 pm and 2.40 pm, each with its
    own minutes.
"""

from __future__ import annotations

import re
from typing import Optional

from aus_council_scrapers.base import ScraperReturn, _merge_split_meetings
from aus_council_scrapers.councilconnect import CouncilConnectScraper

_ELECTORS = re.compile(r"elector", re.IGNORECASE)
_YEAR_AT_EITHER_END = re.compile(r"^\s*(?:19|20)\d{2}\s+|\s+(?:19|20)\d{2}\s*$")
# "ABS" is Donnybrook-Balingup's Agenda Briefing Session.
_BRIEFING_PAPER = re.compile(
    r"briefing|\babs\b|\bq\s*(?:&|and)\s*a\b|qanda", re.IGNORECASE
)
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)
_ORDINARY = re.compile(r"\bordinary\b", re.IGNORECASE)
_DOCUMENTS = ("agenda_url", "minutes_url", "agenda_html_url", "minutes_html_url")


def merge_duplicate_entries(
    results: list[ScraperReturn], logger
) -> list[ScraperReturn]:
    """One record per meeting, where a council entered a meeting twice."""
    results = _merge_split_meetings(results)
    kept: list[ScraperReturn] = []
    by_slot: dict[tuple, ScraperReturn] = {}
    for record in results:
        if record.time is None:
            kept.append(record)
            continue
        key = (record.name, record.date, record.time)
        existing = by_slot.get(key)
        if existing is None:
            by_slot[key] = record
            kept.append(record)
            continue
        logger.info(
            f"{record.name} {record.date} {record.time} is on two pages: "
            f"{existing.webpage_url} and {record.webpage_url}; keeping one"
        )
        papers = lambda r: sum(1 for f in _DOCUMENTS if getattr(r, f))
        if papers(record) > papers(existing):
            kept[kept.index(existing)] = record
            by_slot[key] = record
            record, existing = existing, record
        for field in _DOCUMENTS + ("location",):
            if not getattr(existing, field):
                setattr(existing, field, getattr(record, field))
        existing.download_url = existing.agenda_url or existing.minutes_url
    return kept


def _hour(time: str) -> int:
    """The 24-hour hour of a time the base writes as "5:30 PM"."""
    clock_time, half = time.split()
    return int(clock_time.split(":")[0]) % 12 + (12 if half == "PM" else 0)


class WATidyCouncilConnectScraper(CouncilConnectScraper):
    """`CouncilConnectScraper` with the tidy-ups above; see the module."""

    name_by_type: bool = False
    # See "An hour before a council ever meets is a typo" in the module.
    earliest_hour: Optional[int] = None

    def _name(self, heading, type_slug, labels):
        types = self.meeting_types or {}
        if not self.name_by_type or type_slug not in types:
            return super()._name(heading, type_slug, labels)
        if _ELECTORS.search(heading or ""):
            return _YEAR_AT_EITHER_END.sub(
                "", super()._name(heading, type_slug, labels)
            )
        # A heading that says which kind of Council meeting it is outranks
        # the type it was filed under, both ways round.
        for kind in (_SPECIAL, _ORDINARY):
            if kind.search(heading or ""):
                named = next((n for n in types.values() if kind.match(n)), None)
                if named:
                    return named
        return types[type_slug]

    def _before_earliest_hour(self, time: Optional[str]) -> bool:
        return bool(
            time and self.earliest_hour is not None and _hour(time) < self.earliest_hour
        )

    def _pick_documents(self, links):
        return super()._pick_documents(
            [
                (group, label, url)
                for group, label, url in links
                if not _BRIEFING_PAPER.search(
                    f"{label} {url.rsplit('/', 1)[-1].replace('-', ' ')}"
                )
            ]
        )

    def scraper(self) -> list[ScraperReturn]:
        results = super().scraper()
        for record in results:
            if record.time == "12:00 AM" or self._before_earliest_hour(record.time):
                record.time = None
        return merge_duplicate_entries(results, self.logger)
