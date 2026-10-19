"""Clean-ups for CouncilConnect councils whose pages need them.

These belong in `CouncilConnectScraper` itself, and are kept apart only so
that adding them did not rewrite every existing CouncilConnect fixture at
once. Councils opt in by subclassing `TidyCouncilConnectScraper` instead.

- **Placeholder times.** A meeting entered without a time shows midnight in
  its date field ("Tuesday, March 10, 2020 - 12:00 AM"), and a few were keyed
  as AM for PM ("5:30 AM" for a 5:30 pm meeting at Derby, "12:30 AM" for a
  Katherine meeting headed "12:30pm"). No council meets between midnight and
  6 am, so a time in those hours is dropped rather than published.
- **Names from the meeting type** (`name_by_type`). Where a council's types
  are clean and its headings are not—"Wednesday" for a Geraldton Ordinary
  meeting, "Special Meeting of Council - - 12:30pm" at Katherine,
  "Ordinary Council (Commissioner) Meeting - August 2025" at Derby—the type's
  name is used for every meeting filed under it. Off by default, because some
  councils file a different body under a Council type (Port Hedland's
  electors' meeting under "Special Council Meetings"), and the base's
  heading test is what keeps those apart.
- **Numeric dates in filenames.** Where a meeting page's date field and its
  heading disagree, the base believes the heading only if a document's
  filename names the heading's date, and it reads only spelt-out months
  ("21 December 2021"). Dardanup names its papers "...-10-07-2024.pdf", so
  its 10 July 2024 Special meeting, whose date field says 26 July (the day
  the page was edited), stayed on the 26th. Day-first numeric dates count
  here too.
- **One meeting on two pages.** Councils sometimes create a meeting's page
  twice: Kalgoorlie-Boulder's 16 June 2025 Ordinary meeting (pages 265 and
  274), Dardanup's 27 July 2022 Special meeting (242 and 286). Records with
  the same name, date and agenda file (or minutes file, where there is no
  agenda) are one meeting, and only one is kept: the one whose minutes
  say they are confirmed, over minutes that say neither, over unconfirmed
  or draft minutes or none; between equals, the page created first (the
  lowest id).
- **Filenames that list what is bundled in.** The base drops any file whose
  name says "late" or "notice of motion", even when its label calls it the
  agenda or minutes, because those words usually mean a late item or a
  single report. But Geraldton's 24 March 2020 agenda is
  "agenda-ordinary-meeting-of-council-24-march-2020-website-incl-late-item"
  and Katherine's 27 May 2025 minutes are "...-minutes-confirmed-including-
  207-report-and-notice-of-motion": the whole agenda and the whole minutes,
  saying what they include. So where the label names the agenda or minutes,
  the "incl..." tail of the filename is left out of the base's file test,
  provided what comes before it still names the agenda or minutes. A late
  item that says what it bundles ("late-item-agenda-incl-attachments") is
  still a late item, because the test still sees "late-item-agenda".
- **Corrections for one page** (`page_corrections`). A few pages carry a
  wrong field the papers themselves correct—a time the minutes contradict, or
  another meeting's papers filed on the page. `{page url: {field: value,
  "why": ...}}` overrides those fields on the record read from that page.
  Each entry was checked against the documents' front pages.
"""

from __future__ import annotations

import dataclasses
import datetime
import re
from typing import Optional
from urllib.parse import urlparse

from aus_council_scrapers.base import ScraperReturn
from aus_council_scrapers.councilconnect import (
    _AGENDA,
    _MINUTES,
    CouncilConnectScraper,
)

_SMALL_HOURS = re.compile(r"^(?:12|[1-5]):\d{2}\s*AM$", re.IGNORECASE)
# "10 07 2024", "10072024" once the base has turned separators into spaces.
_NUMERIC_DATE = re.compile(r"(?<!\d)(\d{1,2}) ?(\d{2}) ?(\d{4})(?!\d)")
_UNCONFIRMED = re.compile(r"unconfir|draft", re.IGNORECASE)
# "-incl-late-item", "-including-207-report-and-notice-of-motion", up to the
# extension; see the module doc.
_BUNDLED_TAIL = re.compile(
    r"[-_ ]incl(?:udes?|uding)?[-_ ].*?(?=\.pdf$|$)", re.IGNORECASE
)


def _filename(url):
    return urlparse(url).path.rsplit("/", 1)[-1].lower() if url else None


def _page_id(meeting: ScraperReturn) -> int:
    tail = meeting.webpage_url.rstrip("/").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else 0


class TidyCouncilConnectScraper(CouncilConnectScraper):
    name_by_type: bool = False
    page_corrections: dict[str, dict] = {}

    @staticmethod
    def _parse_when(text: str):
        date, time = CouncilConnectScraper._parse_when(text)
        if time and _SMALL_HOURS.match(time):
            time = None
        return date, time

    @staticmethod
    def _names_date(text: str, date: datetime.date) -> bool:
        if CouncilConnectScraper._names_date(text, date):
            return True
        for day, month, year in _NUMERIC_DATE.findall(text):
            try:
                if datetime.date(int(year), int(month), int(day)) == date:
                    return True
            except ValueError:
                continue
        return False

    @staticmethod
    def collapse_duplicates(meetings: list[ScraperReturn]) -> list[ScraperReturn]:
        """One record per meeting created on two pages; see the module doc."""

        def key(m):
            return (m.name, m.date, _filename(m.agenda_url) or _filename(m.minutes_url))

        def rank(m):
            # Minutes called confirmed, then minutes that say neither, then
            # unconfirmed or draft minutes, or none.
            name = _filename(m.minutes_url) or ""
            if not name or _UNCONFIRMED.search(name):
                status = 2
            elif "confirm" in name:
                status = 0
            else:
                status = 1
            return (status, _page_id(m))

        best = {}
        for m in meetings:
            k = key(m)
            if k not in best or rank(m) < rank(best[k]):
                best[k] = m
        kept = {id(m) for m in best.values()}
        return [m for m in meetings if id(m) in kept]

    def scraper(self) -> list[ScraperReturn]:
        meetings = super().scraper()
        kept = self.collapse_duplicates(meetings)
        for m in meetings:
            if m not in kept:
                self.logger.info(
                    f"Second page for one meeting dropped: {m.webpage_url}"
                )
        return kept

    def _pick_documents(self, links):
        """The base's choice, with bundled-in tails left out of the file
        test; see the module doc. A link whose filename is trimmed goes to
        the base under a stand-in URL, which is swapped back afterwards."""
        real = {url for _, _, url in links}
        stand_ins, tested = {}, []
        for group, label, url in links:
            if url in self.wrong_documents:
                continue
            if _AGENDA.search(label) or _MINUTES.search(label):
                parsed = urlparse(url)
                folder, _, filename = parsed.path.rpartition("/")
                trimmed = _BUNDLED_TAIL.sub("", filename)
                stand_in = parsed._replace(path=f"{folder}/{trimmed}").geturl()
                if (
                    trimmed != filename
                    and (_AGENDA.search(trimmed) or _MINUTES.search(trimmed))
                    and stand_in not in real
                    and stand_in not in stand_ins
                ):
                    stand_ins[stand_in] = url
                    url = stand_in
            tested.append((group, label, url))
        agenda_url, minutes_url = super()._pick_documents(tested)
        return stand_ins.get(agenda_url, agenda_url), stand_ins.get(
            minutes_url, minutes_url
        )

    def _meeting_from_detail(
        self, url: str, labels: dict, fallback_when=None
    ) -> Optional[ScraperReturn]:
        meeting = super()._meeting_from_detail(url, labels, fallback_when)
        fix = self.page_corrections.get(url.rstrip("/"))
        if meeting is None or not fix:
            return meeting
        fields = {k: v for k, v in fix.items() if k != "why"}
        self.logger.info(f"Corrected {url}: {fields} ({fix.get('why')})")
        return dataclasses.replace(meeting, **fields)

    def _name(self, heading, type_slug, labels):
        if self.name_by_type and type_slug and labels.get(type_slug):
            return labels[type_slug]
        return super()._name(heading, type_slug, labels)
