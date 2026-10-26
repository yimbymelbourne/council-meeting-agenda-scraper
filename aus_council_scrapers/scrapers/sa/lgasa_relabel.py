"""LGA SA councils whose committee labels or titles need correcting first.

`LGASAFunnelbackScraper` groups documents on the committee label they are
filed under. A few councils file under a label that names the page rather
than a body, or file single released items that look like a meeting's papers
when nothing else was filed that day. This subclass fixes the listed
documents before the base class assembles them, and changes nothing else:
fetching, crawl delay, classification and pairing are all the base class's.

Three fixes apply to every council here, because each was found on a
council's real documents and none can misfire on another's:

- A notice of adjournment is dropped. "Notice of Adjournment of Committee
  Meeting 9 November 2020" (Port Pirie) says the meeting did not go ahead
  for want of a quorum; the base class reads "notice of ... meeting" as a
  notice of meeting, which is an agenda, so it became that meeting's agenda.
  Victor Harbor's "Disability Access and Inclusion Advisory Committee - 6
  August 2026 - Meeting Adjourned Due to Lack of Quorum" is the same notice
  and became the minutes. Only the *notice* goes: "Notice of Adjourned
  Meeting" is the agenda of the resumed sitting (Whyalla's audit committee,
  29 July 2024, is a 5.4 MB agenda under that title), and "Agenda - 17
  August 2026 - Meeting adjourned due to lack of quorum" (Port Lincoln) is
  the agenda as issued.
- A revised document replaces the original. Latrobe filed "Agenda - 28 April
  2025" (400 pages) and "Revised Agenda - 28 April 2025" (416 pages) under
  the same meeting; the base class picks the lower asset id, the original.
  When two documents of one committee and date have the same title but for
  "revised" or "updated", the original is dropped.
- A listing that cannot be read fails the run when the council has more
  than one. The base class only fails when every listing does, and logs the
  rest; but each listing here is the only source for its body (Murray
  Bridge's assessment panel, Alexandrina's), so a run that lost one would
  report a short list as complete.

The rest are off unless a council sets them:

- `title_labels`: labels under which more than one body is filed. Whyalla
  files its council meetings, audit committee, CEO review panel and briefing
  sessions all under "Whyalla City Council Meetings"; Port Lincoln files the
  Eyre Peninsula Regional Assessment Panel under "Minutes & Agendas". A
  document under one of these labels takes its body from its title: the
  first of `title_bodies` whose pattern matches, or else no label at all,
  which the base class reads as the council itself unless the title names
  another body filed that year (`LGASAFunnelbackScraper._title_body`).
- `relabel`: (label, title pattern, new label) for a body's document filed
  under another body's label. Port Pirie filed the notice of its Access and
  Inclusion Reference Group meeting of 24 February 2026 under "Information
  or Briefing Sessions", which named that meeting a briefing session.
- `exclude_titles`: titles that are never a meeting's agenda or minutes on
  that council's collection, such as Victor Harbor's single resolutions
  "released from confidence". Filed alone under a date, one of them becomes
  a meeting that never happened.
- `title_fixes`: substitutions applied to titles before they are read, for a
  phrase that trips the base class's exclusions on a real document.
- `drop_stray_years`: drop a document whose title states a date in another
  year, more than a month from the date it is filed under. Whyalla filed
  "Informal Gathering Agenda - 3 December 2018" under 3 January 2021, and
  Port Lincoln "Minutes - 21 February 2022 - Confidential Released" under
  21 February 2026; each made a meeting on the filed date. The base class
  trusts a filed date over the title, rightly in general (titles carry year
  typos as often as filed dates do), so this is opt-in per council, where
  the cases have been read.
- `title_dated_committees`: committees whose documents are dated by the
  date in their title, not the date they are filed under. Port Lincoln files
  each briefing-session notice under a date it chooses, usually the
  session's but not always: "9/2/2026 - Closed to Public - Elected Member
  Workshop" is filed under 3 February, and the notice inside says Monday 9
  February. The title is the session's date in all 76 since 2020.
- `special_from_filename`: mark a document as a special meeting's when only
  its file name says so. Latrobe titles every paper "Agenda - 7 September
  2026" and names the special meetings only in the uploaded file,
  "Agenda-Special-Meeting-7-September-2026-inline.pdf", and the base class
  reads the kind of sitting from titles.
- `combined_documents`: a document titled as both the agenda and the
  minutes is put in both slots. Port Augusta's advisory groups publish one
  PDF per meeting, "Aboriginal Community Advisory Group Agenda & Minutes -
  03/02/2025": the notice and agenda, then the minutes of that same meeting
  (read 20 Oct 2026). The base class takes a title naming both kinds as
  naming neither, and drops it when the title has no sitting word either,
  which lost three of that group's meetings in 2025.
"""

from __future__ import annotations

import dataclasses
import datetime
import re
from typing import Optional

from aus_council_scrapers.base import ScraperReturn
from aus_council_scrapers.lgasa import (
    LGASAFunnelbackScraper,
    _AGENDA_WORD,
    _MINUTES_WORD,
    _Listed,
    _Meeting,
    _title_date,
)

# "Special" as a word in a file name, where "_" and "-" separate words.
_SPECIAL_FILE = re.compile(r"(?<![a-z])special(?![a-z])", re.IGNORECASE)
# A title that already names its kind of sitting.
_SITTING_KIND = re.compile(r"\bspecial\b|\bannual general\b|\bAGM\b", re.IGNORECASE)

# "Notice of Adjournment", "Notice - Adjournment", "Adjournment Notice":
# the noun, which only a notice that the meeting will not sit uses.
_ADJOURNMENT_NOTICE = re.compile(
    r"\bnotice\W+(?:of\W+)?adjournment\b|\badjournment\W+notice\b", re.IGNORECASE
)
# "Meeting Adjourned Due to Lack of Quorum" on a title naming neither kind.
_ADJOURNED_FOR_QUORUM = re.compile(
    r"\badjourned\b.{0,20}\b(?:due|for want|lack)\b", re.IGNORECASE
)

# The words a revised upload adds to the original's title.
_REVISION = re.compile(r"\b(?:revised|updated)\b", re.IGNORECASE)

# "Agenda & Minutes", "Agenda and MInutes": one document holding both.
_BOTH_KINDS = re.compile(r"\bagenda\s*(?:&|and)\s*minutes\b", re.IGNORECASE)

# How far a title date may move a document from its filed date; beyond this
# the title more likely carries a typo than the filed date.
_TITLE_DATE_DAYS = 62


def _revision_key(title: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", _REVISION.sub(" ", title).lower()))


class RelabellingLGASAScraper(LGASAFunnelbackScraper):
    # Committee labels that name a page, not one body.
    title_labels: frozenset[str] = frozenset()

    # (title pattern, label) for documents under a `title_labels` label,
    # tried in order. A label of None drops the document: it is filed with
    # the meetings but is not one (Whyalla's councillor training sessions).
    title_bodies: tuple[tuple[re.Pattern, Optional[str]], ...] = ()

    # (label, title pattern, new label): one body's document filed under
    # another's label.
    relabel: tuple[tuple[str, re.Pattern, str], ...] = ()

    # Titles that are never the agenda or the minutes of a meeting.
    exclude_titles: Optional[re.Pattern] = None

    # (pattern, replacement) applied to every title before anything else.
    title_fixes: tuple[tuple[re.Pattern, str], ...] = ()

    # Drop documents whose title dates them to another year; see above.
    drop_stray_years: bool = False

    # Committees whose documents are dated by their titles; see above.
    title_dated_committees: frozenset[str] = frozenset()

    # Read "Special" from the file name when the title gives no kind of
    # sitting; see above.
    special_from_filename: bool = False

    # Put an "Agenda & Minutes" document in both slots; see above.
    combined_documents: bool = False

    def scraper(self) -> list[ScraperReturn]:
        self._failed_listings: list[str] = []
        self._combined: set[str] = set()
        records = super().scraper()
        if self._failed_listings:
            raise RuntimeError(
                f"{self.council_name}: could not read "
                f"{', '.join(self._failed_listings)}, the only listing for "
                f"its bodies; the other listings were read"
            )
        return records

    def _read_listing(self, listing_url: str, earliest_year: int) -> list[_Listed]:
        """The listed documents, before any fix. A subclass with a page
        that is not a Funnelback listing reads it here."""
        return super()._listing_documents(listing_url, earliest_year)

    def _listing_documents(self, listing_url: str, earliest_year: int) -> list[_Listed]:
        try:
            listed = self._read_listing(listing_url, earliest_year)
        except Exception:
            self._failed_listings.append(listing_url)
            raise
        documents = []
        for document in listed:
            fixed = self._fix(document)
            if fixed is not None:
                documents.append(fixed)
        return self._drop_superseded(documents)

    def _fix(self, listed: _Listed) -> Optional[_Listed]:
        title = listed.title
        for pattern, replacement in self.title_fixes:
            title = pattern.sub(replacement, title).strip()
        if self.exclude_titles and self.exclude_titles.search(title):
            return None
        if _ADJOURNMENT_NOTICE.search(title) or (
            _ADJOURNED_FOR_QUORUM.search(title)
            and not _AGENDA_WORD.search(title)
            and not _MINUTES_WORD.search(title)
        ):
            return None
        if self.drop_stray_years and listed.date and self._stray(title, listed.date):
            return None
        if (
            self.special_from_filename
            and _SPECIAL_FILE.search(listed.filename)
            and not _SITTING_KIND.search(title)
        ):
            title = f"{title} - Special Meeting"
        if self.combined_documents and _BOTH_KINDS.search(title):
            # Read as the agenda; `_records` adds it as the minutes too.
            title = _BOTH_KINDS.sub("Agenda", title)
            self._combined.add(listed.asset_id)
        date = listed.date
        if listed.committee in self.title_dated_committees and date:
            stated = _title_date(title)
            filed = datetime.date.fromisoformat(date)
            if stated and abs((stated - filed).days) <= _TITLE_DATE_DAYS:
                date = stated.isoformat()
        committee = listed.committee
        for label, pattern, new_label in self.relabel:
            if committee == label and pattern.search(title):
                committee = new_label
                break
        if committee in self.title_labels:
            committee = ""
            for pattern, label in self.title_bodies:
                if pattern.search(title):
                    if label is None:
                        return None
                    committee = label
                    break
        return dataclasses.replace(listed, title=title, committee=committee, date=date)

    @staticmethod
    def _drop_superseded(documents: list[_Listed]) -> list[_Listed]:
        """Drop an original whose revised upload is filed beside it."""
        revised = {
            (d.committee, d.date, _revision_key(d.title))
            for d in documents
            if _REVISION.search(d.title)
        }
        return [
            d
            for d in documents
            if _REVISION.search(d.title)
            or (d.committee, d.date, _revision_key(d.title)) not in revised
        ]

    def _records(self, meetings: list[_Meeting]) -> list[ScraperReturn]:
        records = super()._records(meetings)
        if self._combined:
            combined = {self._document_url(a) for a in self._combined}
            for record in records:
                if record.minutes_url is None and record.agenda_url in combined:
                    record.minutes_url = record.agenda_url
        return records

    @staticmethod
    def _stray(title: str, filed: str) -> bool:
        stated = _title_date(title)
        if stated is None:
            return False
        filed_on = datetime.date.fromisoformat(filed)
        return stated.year != filed_on.year and abs((stated - filed_on).days) > 31
