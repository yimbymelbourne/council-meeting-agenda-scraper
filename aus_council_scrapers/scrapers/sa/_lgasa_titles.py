"""LGA SA councils whose document titles have to correct the listing.

Six small regional councils (Coober Pedy, Wudinna, Kimba, Elliston,
Karoonda East Murray, Orroroo Carrieton) publish into the same Funnelback
collections as every `LGASAFunnelbackScraper` council, but their
listings go wrong in three ways the base class does not handle. Each is
fixed here from the document's title, which on these sites is written by the
person who uploaded it and is right more often than the listing's metadata.

1. **Other sittings under the council label.** Kimba files a "Council
   Workshop Agenda" and "Council Workshop Minutes" beside the council
   meeting's papers on the same date, under the same committee, and Karoonda
   East Murray files its briefing-session notices the same way. Grouped on
   committee and date, the workshop agenda has the lower asset id and became
   the council meeting's agenda. `title_bodies` moves those documents to a
   body of their own (or drops them) before grouping.

2. **"+ Attachments".** Coober Pedy titled its whole agendas and minutes
   "Agenda 13 December 2023 + Attachments" for two years. The base class
   treats any title with "attachment" in it as an attachment unless it reads
   "agenda and attachments" with nothing between, so those meetings lost both
   papers. The "+ Attachments" token is removed before classification; the
   separately uploaded attachments ("Minutes 8 March 2022 - Attachment 1")
   are untouched and still excluded.

3. **A meeting date filed wrong.** The meeting date is typed in by hand.
   A month slip is common enough to matter: Coober Pedy's "Agenda for the
   Ordinary Meeting of Council - 26 June 2024" is filed under 26 July,
   Elliston's "Ordinary Council Meeting Agenda - 15 July 2025" under 15 June,
   Wudinna's "15 June 2021 Minutes" under 15 July. The base class rejoins an
   agenda and minutes up to a fortnight apart, so these came out as two
   meetings, one of them on a date nobody met; and where both papers carry the
   same wrong date (Coober Pedy's 27 August 2025 meeting, filed under the
   28th) nothing rejoins anything. Three corrections, in order:

   - A title that states a full date up to `_SLIP_DAYS` from the filed one
     moves the document to the title's date.
   - A title naming only a month and year ("August 2020 Agenda", filed 18
     July) moves the document onto a date the same body already has
     documents for in that month, and only when there is exactly one such
     date. The day always comes from the listing, never from a guess.
   - An agenda whose title gives no day, filed on a date with no minutes of
     its body, moves to the one date up to `_NOTICE_DAYS` later that has
     that body's minutes and no agenda. Wudinna files some agendas under the
     date of the notice: "February 2025 Agenda" is filed under 12 February,
     and its PDF calls the meeting for 18 February, where the minutes are.

A title that names a month other than the meeting's also ranks behind one
that does not. Orroroo Carrieton filed "Council Meeting Minutes December 2022
(held 25 Jan 2023)" beside the minutes of its 25 January 2023 meeting, and on
asset id alone it was chosen as that meeting's minutes.

Three more rules, each for something these listings do that the base class
lets through:

- **A listing entry with no file is dropped.** The base class falls back to
  the click-tracking asset id when an entry has no `/__data/assets/` URL.
  Every such entry dated 2020 or later on these six listings is a dead stub:
  Wudinna's "December 2020 Agenda" (?a=818422) and "Town Development and
  Amenities Committee Agenda 0522" (?a=1146708), and Elliston's "EPRAP Agenda
  10 August 2020" (?a=727099) and "Ordinary Council Meeting Agenda - 21
  January 2025" (?a=1742067) each served 0 bytes of text/html when fetched
  on 20 Oct 2026. Where nothing else was filed for the meeting, the base
  class's PDF-first tie-break cannot save it, and the stub became the agenda.
- **A re-upload marked "updated" or "amended" replaces the original.**
  Orroroo Carrieton's "Council Meeting Agenda 22 April 2026 *Updated*" is
  227 pages to the original's 220, and was losing to it on asset id. The
  base class ranks "amended" behind a clean title, and an "Amended
  Attachment Item 13.6" should stay behind the agenda, so a revision is
  preferred only when, with the mark taken out, its title is the same as
  the sibling it replaces.
- **Every listing must be read.** The base class raises only when every
  listing page failed. Kimba, Elliston and Karoonda East Murray read two, and
  a Cloudflare challenge can clear for one request and not the next, so a
  lost council page would otherwise report success with only the assessment
  panel's meetings, or none.

**robots.txt.** The six hosts served the same Matrix default robots.txt as
the base class's councils when checked on 20 Oct 2026 (`Crawl-delay: 20`,
`Disallow: /search`, `*?*query=`, `*?*f.*%7C*=`); `lgasa.py`'s module
docstring, which counts "ten council hosts", predates them.

The base class's own rules still run afterwards, on the corrected listing.
"""

from __future__ import annotations

import dataclasses
import datetime
import re
from typing import Optional

from aus_council_scrapers.lgasa import (
    LGASAFunnelbackScraper,
    _classify,
    _Document,
    _Listed,
    _Meeting,
    _MONTHS,
    _title_date,
)

# Coober Pedy's "Agenda 28 June 2023 + Attachments", "Minutes 24 May 2023 +
# attachments". Only the "+" form: "Minutes 8 March 2022 - Attachment 1" is an
# attachment and must stay one.
_PLUS_ATTACHMENTS = re.compile(r"\s*\+\s*attachments?\b", re.IGNORECASE)

# "August 2020", "June 2021", and the month and year of a full date.
_MONTH_YEAR = re.compile(rf"\b({_MONTHS})\.?,?[\s-]+(\d{{4}})\b", re.IGNORECASE)

# A title's full date replaces a filed date up to this far from it. Further
# than this it is more likely the title that is wrong: Orroroo Carrieton's
# "Council Meeting Agenda 25 March 2025" is the agenda of 25 March 2026, a
# year out. See the module docstring.
_SLIP_DAYS = range(1, 46)

# How far ahead of its meeting an agenda may be filed under its notice date;
# see `_move_notice_dated_agendas`. South Australian councils give at least
# three clear days' notice, and these give about a week.
_NOTICE_DAYS = range(1, 11)


# "Agenda 26 August 2026 - updated", "Council Meeting Agenda 22 April 2026
# *Updated*", "Amended Agenda 13 December 2022", "Minutes 24 August 2021 -
# Amended". The mark with whatever joins it to the rest of the title.
_REVISION_MARK = re.compile(
    r"[\s*()\-–]*\b(?:updated|amended)\b[\s*()\-–]*", re.IGNORECASE
)


def _unrevised(title: str) -> str:
    """A title with any revision mark taken out, for comparing siblings."""
    return " ".join(_REVISION_MARK.sub(" ", title).lower().split())


def _month_number(name: str) -> int:
    return datetime.datetime.strptime(name[:3], "%b").month


def _title_months(title: str) -> set[tuple[int, int]]:
    """(year, month) for every month a title names, with or without a day."""
    months = {
        (int(year), _month_number(month)) for month, year in _MONTH_YEAR.findall(title)
    }
    stated = _title_date(title)
    if stated:
        months.add((stated.year, stated.month))
    return months


def _month_only(title: str) -> Optional[tuple[int, int]]:
    """The (year, month) of a title that names one month and no full date."""
    if _title_date(title):
        return None
    months = {
        (int(year), _month_number(month)) for month, year in _MONTH_YEAR.findall(title)
    }
    return months.pop() if len(months) == 1 else None


class TitleCorrectedLGASAScraper(LGASAFunnelbackScraper):
    """`LGASAFunnelbackScraper`, with the listing corrected from titles.

    A subclass sets the base class's attributes as usual, plus
    `title_bodies` for sittings that are filed under the council's label but
    are not council meetings.
    """

    # (pattern, body): a document whose title matches is grouped as a meeting
    # of that body, whatever committee it was filed under; a body of None
    # drops the document. The first matching pattern wins.
    title_bodies: tuple[tuple[re.Pattern, Optional[str]], ...] = ()

    def scraper(self):
        # Listings whose read failed in this run; see `_listing_documents`.
        self._failed_listings: list[str] = []
        records = super().scraper()
        if self._failed_listings:
            # The base class has logged each failure and returned what the
            # other listings held. A run that lost the council's own page
            # would look like a council that held no meetings, or only its
            # panel's, so it fails instead; see the module docstring.
            raise RuntimeError(
                f"{self.council_name}: could not read "
                f"{', '.join(self._failed_listings)}; not returning the "
                f"{len(records)} meetings the other listings held as if "
                f"they were all of them"
            )
        return records

    def _listing_documents(self, listing_url: str, earliest_year: int) -> list[_Listed]:
        """The listing, with titles cleaned, bodies reassigned and slips moved.

        Done here, before the base class sorts documents into years, so that a
        slip across New Year moves the document into the right year too:
        Coober Pedy's "Notice of Information and Briefing Session 14 January
        2025" is filed under 24 December 2024.
        """
        try:
            listing = super()._listing_documents(listing_url, earliest_year)
        except Exception:
            getattr(self, "_failed_listings", []).append(listing_url)
            raise
        documents = []
        for listed in listing:
            if not listed.asset_type:
                # No file behind it: a dead stub. See the module docstring.
                continue
            title = _PLUS_ATTACHMENTS.sub("", listed.title)
            committee = listed.committee
            for pattern, body in self.title_bodies:
                if pattern.search(title):
                    committee = body
                    break
            if committee is None:
                continue
            date = listed.date
            stated = _title_date(title)
            if (
                date
                and stated
                and abs((stated - datetime.date.fromisoformat(date)).days) in _SLIP_DAYS
            ):
                date = stated.isoformat()
            documents.append(
                dataclasses.replace(listed, title=title, committee=committee, date=date)
            )
        return documents

    def _move_month_only(self, documents: list[_Listed], year: int) -> list[_Listed]:
        """Move a document titled only with another month onto that month's
        one meeting of the same body, if it has exactly one."""
        moved = []
        for listed in documents:
            month = _month_only(listed.title)
            if listed.date and month and month != (year, int(listed.date[5:7])):
                body = self._body_name(listed.committee)
                dates = {
                    other.date
                    for other in documents
                    if other is not listed
                    and other.date
                    and (int(other.date[:4]), int(other.date[5:7])) == month
                    and self._body_name(other.committee) == body
                }
                if len(dates) == 1:
                    listed = dataclasses.replace(listed, date=dates.pop())
            moved.append(listed)
        return moved

    def _move_notice_dated_agendas(self, documents: list[_Listed]) -> list[_Listed]:
        """Move an agenda filed under its notice date onto its meeting's date.

        See the module docstring. An agenda titled with its full date is left
        where the title puts it.
        """

        def kind(listed: _Listed) -> Optional[str]:
            classified = _classify(listed.title, listed.filename)
            return classified[0] if classified else None

        papers: dict[tuple[str, str], set[str]] = {}
        for listed in documents:
            if listed.date:
                key = (self._body_name(listed.committee), listed.date)
                papers.setdefault(key, set()).add(kind(listed))

        moved = []
        for listed in documents:
            body = self._body_name(listed.committee)
            if (
                listed.date
                and kind(listed) == "agenda"
                and not _title_date(listed.title)
                and "minutes" not in papers.get((body, listed.date), set())
            ):
                filed = datetime.date.fromisoformat(listed.date)
                later = [
                    date
                    for (other_body, date), kinds in papers.items()
                    if other_body == body
                    and (datetime.date.fromisoformat(date) - filed).days in _NOTICE_DAYS
                    and "minutes" in kinds
                    and "agenda" not in kinds
                ]
                if len(later) == 1:
                    listed = dataclasses.replace(listed, date=later[0])
            moved.append(listed)
        return moved

    def _assemble(self, documents: list[_Listed], year: int) -> list[_Meeting]:
        documents = self._move_notice_dated_agendas(
            self._move_month_only(documents, year)
        )
        meetings = super()._assemble(documents, year)
        for meeting in meetings:
            month = (int(meeting.date[:4]), int(meeting.date[5:7]))
            for document in meeting.agendas + meeting.minutes + meeting.unnamed:
                if _title_months(document.title) - {month}:
                    document.rank += 1
            for candidates in (meeting.agendas, meeting.minutes):
                _prefer_revisions(candidates)
        return meetings


def _prefer_revisions(candidates: list[_Document]) -> None:
    """Rank a re-upload marked "updated" or "amended" ahead of the original.

    Only when the two titles are the same with the mark taken out, so an
    "Amended Attachment Item 13.6" or an amended notice never displaces the
    agenda; see the module docstring. The revision takes the original's rank,
    and the original drops one behind it.
    """
    for revision in candidates:
        if not _REVISION_MARK.search(revision.title):
            continue
        originals = [
            other
            for other in candidates
            if other is not revision
            and not _REVISION_MARK.search(other.title)
            and _unrevised(other.title) == _unrevised(revision.title)
        ]
        if originals:
            revision.rank = min(other.rank for other in originals)
            for other in originals:
                other.rank = revision.rank + 1
