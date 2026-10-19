"""Title rules for small LGA SA councils whose committee labels mislead.

Everything about fetching, robots.txt, the crawl delay and assembling
meetings is in `aus_council_scrapers/lgasa.py`. The base class trusts two
things a document is filed with: its committee label and its meeting date.
On the councils it was built against both were mostly right. On the small
regional councils here they often are not, and the title is what says so:

- **Papers that are not a meeting's agenda or minutes, titled as if they
  were.** Tumby Bay files its information briefing sessions, the notices of
  them and its released confidential items under the same label as its
  council meetings ("Information Briefing Session - 27 January 2026"), and
  Kingston and Cleve file a "Notice of Adjourned Council Meeting" beside the
  agenda. Each became a "Council Meeting" that never happened, or replaced a
  meeting's real agenda. `skip_titles` drops them before grouping.
- **Another body's papers under the council's label.** Tumby Bay's "CEO
  Performance Review Committee Meeting Agenda" and Barunga West's "Audit
  Committee Minutes" are filed as council papers, which put another body's
  minutes on a council meeting. `refile` moves a document to the committee
  its title names.
- **A title the base class reads the wrong way.** Southern Mallee titles
  every agenda "Notice of Council Meeting and Agenda", and the word "notice"
  ranks it as a lesser candidate, so on a day with an ordinary and a special
  meeting the base class could not tell there were two. `retitle` rewrites
  the title the classification reads. Titles are never emitted, so this
  changes only which document is chosen.
- **A meeting date typed wrong.** The listing's date is typed by hand per
  document. Barunga West filed its 9 February 2021 minutes under 9 January
  and its 13 June 2023 agenda under 13 July, a month from their meetings,
  so the base class's own rejoining (`_rejoin_misdated`, a fortnight at
  most) left each meeting split in two. With `title_dates`, a document is
  grouped under the full date its title states when that is more than a
  fortnight and at most `TITLE_DATE_WINDOW_DAYS` from the filed date, in
  the same year, unless the uploaded file's name states the filed date: then
  the filed date stands. Closer than a fortnight is left to the base class,
  which joins only an agenda-only and a minutes-only meeting of one name;
  moving a paper a day can instead drop it into another sitting that week
  (Barunga West's "Special Council Meeting Minutes 10 March 2020", filed
  under the 11th, would have joined that day's ordinary meeting and been
  lost behind its minutes). A council can widen the window with
  `title_date_window_days` where every disagreement was checked (Flinders
  Ranges). The base class does not do this for every council because of
  one Derwent Valley paper, an LGAT AGM agenda attached to a council meeting
  whose title names the AGM's date; it is opt-in here for councils whose
  titles were checked against their filed dates.
- **A lesser paper the base class ranks first.** Flinders Ranges files
  each agenda twice, "Agenda Only" (the order of business) and "Agenda,
  Reports & Attachments" (the full papers). The base class drops the second
  as an attachment, so the agenda emitted was the one without the reports.
  `retitle` lets the full papers be read as the agenda, and `demote` ranks
  the order of business behind them (by its title, or by its file name where
  the title does not say: "FRAP Agenda 23 November 2021", uploaded as
  "...-Agenda-Only.pdf"), so it is chosen only when it is all that was
  filed.

- **A paper re-released in full beside the version first published.**
  Barunga West published the 28 April 2023 special meeting's minutes with
  its confidential item withheld, then filed the full minutes once the
  confidentiality order was lifted ("... Minutes (Conf. order lifted)").
  The base class read the extra words as a second sitting that day and
  emitted the meeting twice. `supersede` marks the re-released version: it
  replaces the paper of the same date, label and title without the mark.

The first five are applied to the listed documents in `_listing_documents`,
after the base class has read them, so fetching and the stop-early rule are
unchanged; `demote` is applied in `_assemble`, after the base class has
ranked each meeting's candidates.

A council with more than one listing page fails outright when its first
page, the council's own meetings, cannot be read. The base class carries on
with the rest and fails only when every page fails, so a Cloudflare
challenge that never cleared on the council's page would have reported only
its assessment panel's meetings, a quietly short list for that night.

A sibling module on another branch, `lgasa_regional.py`
(`RegionalLGASAScraper`), solves the first and the fourth of these for
other regional councils, the first with the same attribute name,
`skip_titles`; the two can be merged.
"""

from __future__ import annotations

import dataclasses
import datetime
import re
from typing import Optional

from aus_council_scrapers.base import ScraperReturn
from aus_council_scrapers.lgasa import (
    _MONTHS,
    LGASAFunnelbackScraper,
    _Listed,
    _Meeting,
    _title_date,
    _words,
)

# The worst misfilings seen are a month out (Barunga West's February 2021
# minutes filed under January). Further than this, a title's date is more
# likely naming some other meeting than correcting this one's.
TITLE_DATE_WINDOW_DAYS = 45

# The farthest apart `lgasa._rejoin_misdated` joins an agenda and its
# minutes whose titles agree on the date. Nearer misfilings are left to it.
REJOIN_DAYS = 14

# "Feb 09 2021 Ordinary Council Meeting Minutes", "Sept 13 2022 Ord Council
# Meeting": Barunga West's month-first titles, which the base class's title
# dates (day first) do not read.
_MONTH_FIRST = re.compile(
    rf"\b({_MONTHS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b",
    re.IGNORECASE,
)

# "2026.09.08 Late Item", "2025.04.08-Minutes-PUBLIC-Ord.pdf".
_ISO_DATE = re.compile(r"\b(20\d\d)[-.](\d{1,2})[-.](\d{1,2})\b")


def stated_date(text: str) -> Optional[datetime.date]:
    """The full date a title or file name states, in any form used here."""
    for pattern, order in ((_ISO_DATE, "ymd"), (_MONTH_FIRST, "mdy")):
        match = pattern.search(text)
        if not match:
            continue
        try:
            if order == "ymd":
                return datetime.date(*(int(part) for part in match.groups()))
            month, day, year = match.groups()
            return datetime.datetime.strptime(
                f"{day} {month[:3]} {year}", "%d %b %Y"
            ).date()
        except ValueError:
            return None
    return _title_date(text)


def _file_date(filename: str) -> Optional[datetime.date]:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return stated_date(stem) or stated_date(_words(stem))


class TitleRulesLGASAScraper(LGASAFunnelbackScraper):
    """`LGASAFunnelbackScraper` with per-council rules read off titles."""

    # Documents to drop before grouping: never a meeting's agenda or
    # minutes, however they are filed.
    skip_titles: Optional[re.Pattern] = None

    # (title pattern, committee label): a document whose title matches is
    # treated as filed under that committee. First match wins. The label
    # then goes through `committee_names` and `skip_committees` as usual.
    refile: tuple[tuple[re.Pattern, str], ...] = ()

    # (pattern, replacement) applied in order to the title the base class
    # classifies. Never emitted.
    retitle: tuple[tuple[re.Pattern, str], ...] = ()

    # Group a document under its title's date; see the module docstring.
    title_dates: bool = False
    # How far from the filed date a title's date is still trusted.
    title_date_window_days: int = TITLE_DATE_WINDOW_DAYS

    # A candidate whose title (as listed) or uploaded file name matches this
    # ranks behind one that does not.
    demote: Optional[re.Pattern] = None

    # The mark of a re-released paper in its title. A document carrying it
    # replaces any document of the same date and label whose title is its
    # own with the mark removed; the mark is then removed from it too.
    supersede: Optional[re.Pattern] = None

    def scraper(self) -> list[ScraperReturn]:
        self._council_listing_error: Optional[Exception] = None
        records = super().scraper()
        if self._council_listing_error is not None and len(self.listing_urls) > 1:
            raise RuntimeError(
                f"{self.council_name}: could not read the council's own listing "
                f"{self.listing_urls[0]}; the other listings alone would be a "
                "short list"
            ) from self._council_listing_error
        return records

    def _listing_documents(self, listing_url: str, earliest_year: int) -> list[_Listed]:
        try:
            documents = super()._listing_documents(listing_url, earliest_year)
        except Exception as error:
            # The base class logs it and carries on; `scraper` raises once
            # the rest have been read. Re-raised so that logging still runs.
            if listing_url == self.listing_urls[0]:
                self._council_listing_error = error
            raise
        tidied = [
            document
            for document in (self._tidy(document) for document in documents)
            if document is not None
        ]
        return self._drop_superseded(tidied) if self.supersede else tidied

    def _drop_superseded(self, documents: list[_Listed]) -> list[_Listed]:
        def unmarked(title: str) -> str:
            return self.supersede.sub("", title).strip()

        released = {
            (d.date, d.committee, unmarked(d.title))
            for d in documents
            if self.supersede.search(d.title)
        }
        kept = []
        for document in documents:
            if self.supersede.search(document.title):
                kept.append(
                    dataclasses.replace(document, title=unmarked(document.title))
                )
            elif (document.date, document.committee, document.title) not in released:
                kept.append(document)
        return kept

    def _assemble(self, documents: list[_Listed], year: int) -> list[_Meeting]:
        meetings = super()._assemble(documents, year)
        if self.demote:
            demoted = {
                d.asset_id
                for d in documents
                if self.demote.search(d.title) or self.demote.search(d.filename)
            }
            for meeting in meetings:
                for document in meeting.agendas + meeting.minutes:
                    if document.asset_id in demoted:
                        document.rank += 1
        return meetings

    def _tidy(self, document: _Listed) -> Optional[_Listed]:
        if self.skip_titles and self.skip_titles.search(document.title):
            return None
        changes = {}
        for pattern, committee in self.refile:
            if pattern.search(document.title):
                changes["committee"] = committee
                break
        title = document.title
        for pattern, replacement in self.retitle:
            title = pattern.sub(replacement, title)
        if title != document.title:
            changes["title"] = title
        if self.title_dates and document.date:
            date = self._title_date_for(document)
            if date != document.date:
                changes["date"] = date
        return dataclasses.replace(document, **changes) if changes else document

    def _title_date_for(self, document: _Listed) -> str:
        filed = datetime.date.fromisoformat(document.date)
        stated = stated_date(document.title)
        if (
            stated is None
            or stated == filed
            or stated.year != filed.year
            or not REJOIN_DAYS
            < abs((stated - filed).days)
            <= self.title_date_window_days
            # 1 January is Matrix's placeholder; the base class handles it.
            or (filed.month, filed.day) == (1, 1)
        ):
            return document.date
        if _file_date(document.filename) == filed:
            return document.date
        return stated.isoformat()
