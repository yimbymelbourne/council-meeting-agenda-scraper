"""DocsPublished councils whose document list cannot be read at face value.

`DocsPublishedScraper` trusts each record's two slots: whatever the council
uploaded as the agenda is the agenda, and the record's date is the meeting's
date. The first seven tenants were built on that. For the eight added after
them it is wrong, in the ways the project cares most about. Checked against
the PDFs' first pages, 20 Oct 2026:

- **A supplementary paper in the agenda slot.** Central Coast filed its
  "Supplementary Attachments Paper" (`... Agenda Attachment SUP.pdf`) as the
  agenda of 24 meetings from 2021 to 2025, 22 of them with the real
  business paper moved into the record's supporting documents. West Daly
  filed a "Supplementary Report" and a "Finance Report" there.
- **Minutes in the agenda slot.** West Daly (four meetings), Albury (two) and
  Pormpuraaw (one) uploaded a second copy of the minutes, or another
  meeting's minutes, as the agenda: Albury's 13 April 2026 "agenda" is the
  minutes of 11 May.
- **A paper filed on the wrong meeting.** Central Coast's record for 11
  February 2022 holds the business paper of 11 October 2022, whose own
  record has only a supplementary paper; Wollondilly's 28 April 2022 panel
  record holds the 28 June agenda. The filename carries the right date and
  the other record exists, so the paper is moved to it.
- **Minutes among the supporting documents.** Groote's 29 September 2025
  meeting and Albury's 1 December 2025 Community Forum have an empty minutes
  slot and their minutes attached as a supporting document.

So this subclass rewrites the document list before the base class reads it,
with five rules applied in order:

1. An agenda slot holding minutes is moved to the minutes slot if that is
   empty, and otherwise dropped.
2. An agenda slot holding a supplementary paper, a report or an attachments
   bundle is dropped. After rule 1 or 2 empties the agenda slot, a
   supporting document that is this meeting's agenda takes it, if the record
   has one.
3. A paper whose filename names a different day, where a record of the same
   meeting type exists on that day, belongs to that record: it moves there if
   that slot is empty, and is dropped here only if that record already holds
   the same file (same name and size). A filename date with no such record is
   left alone, because filenames are wrong too—Pormpuraaw's 20 October 2026
   agenda is filed as "19 October 2026", and the notice inside says the 20th.
4. An agenda-only and a minutes-only record of one meeting type on one day
   become one record.
5. An empty minutes slot, or one holding unconfirmed minutes, takes a
   supporting document whose filename says it is this meeting's minutes.

Every rule only ever removes a paper or moves one the council itself
listed into a slot; none invents one, and a record left with no paper is
skipped by the base class as before. Production cost is unchanged: the same
requests the base class makes, five to eight a council—the organisation,
portal shell, JS bundle, one to four pages of blob listing (Busselton has
four) and the document list.
"""

import datetime
import re
from typing import Optional

import pytz

from aus_council_scrapers.base import DocsPublishedScraper, ScraperReturn
from aus_council_scrapers.constants import TIMEZONES_BY_STATE

_MONTHS = (
    "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?"
    "|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_MONTH_NUMBERS = {
    name: number
    for number, name in enumerate(
        "jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1
    )
}

# Dates as these councils write them into filenames: "20260505 MAY Council
# Meeting" (Northern Grampians), "Ordinary Council 09112021 Agenda" (Central
# Coast), "Agenda - 28 June 2022", "Coastal Minutes 31.3.26".
_YYYYMMDD = re.compile(r"(?<!\d)(20\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")
_DDMMYYYY = re.compile(r"(?<!\d)(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])(20\d\d)(?!\d)")
_D_MONTH_YYYY = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?[\s_.-]+({_MONTHS})\.?[\s_,.-]+(20\d\d)(?!\d)",
    re.I,
)
_D_M_YY = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(20\d\d|\d\d)(?!\d)")

_MINUTES_WORD = re.compile(r"\bminutes?\b|\bmins?\b", re.I)
_UNCONFIRMED = re.compile(r"unconfirmed", re.I)
_AGENDA_WORD = re.compile(r"\bagenda\b|\bagn\b|business paper", re.I)


def filename_date(name: Optional[str]) -> Optional[datetime.date]:
    """The one date a filename names, or None if it names none or several."""
    if not name:
        return None
    found = set()
    for match in _YYYYMMDD.finditer(name):
        found.add(_date(match[1], match[2], match[3]))
    for match in _DDMMYYYY.finditer(name):
        found.add(_date(match[3], match[2], match[1]))
    for match in _D_MONTH_YYYY.finditer(name):
        month = _MONTH_NUMBERS[match[2].lower()[:3]]
        found.add(_date(match[3], month, match[1]))
    for match in _D_M_YY.finditer(name):
        year = int(match[3])
        found.add(_date(year + 2000 if year < 100 else year, match[2], match[1]))
    found.discard(None)
    return found.pop() if len(found) == 1 else None


def _date(year, month, day) -> Optional[datetime.date]:
    try:
        return datetime.date(int(year), int(month), int(day))
    except ValueError:
        return None


def is_minutes(name: Optional[str]) -> bool:
    return bool(name and _MINUTES_WORD.search(name))


def is_not_an_agenda(name: Optional[str]) -> bool:
    """A paper that goes with the agenda but is not it.

    "Agenda Attachment" is Central Coast's (InfoCouncil's) name for the agenda
    with its attachments inline—the full business paper—so attachments only
    count against a file that does not also say it is the agenda.
    """
    if not name:
        return False
    if re.search(
        r"\bsup\b|supplementar|addend|\blate items?\b|items? for debate|\btabled\b",
        name,
        re.I,
    ):
        return True
    if re.search(
        r"\breports?\b|\battachments?\b", name, re.I
    ) and not _AGENDA_WORD.search(name):
        return True
    return False


class CheckedDocsPublishedScraper(DocsPublishedScraper):
    """`DocsPublishedScraper` with the document list checked before use.

    Not registered: a base for the council subclasses, which still supply
    only `publishing_slug` and, where a council needs one, `_meeting_type`.
    """

    # Meeting types that are not meetings. Central Coast published a
    # "TESTING Harbour Software" record during a live-stream trial, whose
    # "agenda" is a test upload.
    skip_types = re.compile(r"\btest(?:ing)?\b", re.I)

    def scraper(self) -> list[ScraperReturn]:
        results = super().scraper()
        for meeting in results:
            # Records entered with a date and no time are stamped at local
            # midnight; "12:00 AM" would claim a start time nobody gave. Other
            # early-morning times are AM/PM slips: Northern Grampians' 23
            # October 2023 meeting is stamped 12:30 AM, and every other one of
            # its meetings starts at 12:30 PM; Wollondilly's 20 August 2018
            # meeting is stamped 6:30 AM and its agenda says 6.30pm. No
            # meeting on these eight councils is stamped between 7 and 9 am,
            # so before 7 is a slip, and gets no time. The date is
            # unaffected: a slip of twelve hours from before 7 am stays on the
            # same day. The base class formats every time as "%I:%M %p".
            if (
                meeting.time
                and datetime.datetime.strptime(meeting.time, "%I:%M %p").hour < 7
            ):
                meeting.time = None
        return results

    def _get_json(self, url: str):
        data = super()._get_json(url)
        if url.startswith(f"{self.API_ROOT}/documents/") and isinstance(data, list):
            return self._checked_documents(data)
        return data

    # ------------------------------------------------------------------

    def _local_date(self, doc: dict) -> Optional[datetime.date]:
        """The record's meeting day, converted as the base class converts it."""
        stamp = doc.get("MeetingDate")
        if not stamp:
            return None
        try:
            utc = datetime.datetime.fromisoformat(stamp).replace(
                tzinfo=datetime.timezone.utc
            )
        except ValueError:
            return None
        tz = pytz.timezone(TIMEZONES_BY_STATE[self.state.upper()])
        return utc.astimezone(tz).date()

    def _meeting_type(self, doc: dict, known_types: list[str]) -> Optional[str]:
        """The record's meeting type, for a council to refine.

        A record with no type takes the longest known type its filename
        contains—Albury left two "Pre-meeting Briefing Session Agenda"
        uploads untyped, alongside 21 typed "Briefing Session". With no match
        it is left empty, and the base class falls back to the title.
        """
        meeting_type = (doc.get("MeetingType") or "").strip()
        if meeting_type:
            return meeting_type
        filename = _paper(doc, "Agenda") or _paper(doc, "Minutes") or ""
        matches = [t for t in known_types if t.lower() in filename.lower()]
        return max(matches, key=len) if matches else None

    def _checked_documents(self, documents: list) -> list:
        known_types = sorted(
            {(d.get("MeetingType") or "").strip() for d in documents} - {""}
        )
        kept = []
        for doc in documents:
            if self.skip_types.search(doc.get("MeetingType") or ""):
                self.logger.info(
                    f"Skipping {doc.get('DocumentTitle')!r}: not a meeting"
                )
                continue
            doc = dict(doc)
            doc["MeetingType"] = self._meeting_type(doc, known_types)
            kept.append(doc)

        for doc in kept:
            self._check_agenda_slot(doc)
        self._move_misfiled_papers(kept)
        joined = self._join_split_records(kept)
        for doc in joined:
            self._check_minutes_slot(doc)
        return joined

    def _join_split_records(self, documents: list) -> list:
        """Fold an agenda-only and a minutes-only record of one meeting.

        Wollondilly entered some meetings twice, the notice on one record and
        the record of proceedings on another of the same type and day. Only
        an exact pair is joined: one record with just an agenda and one with
        just minutes. Two meetings of one body on one day each keep their own.
        """
        groups: dict[tuple, list[dict]] = {}
        for doc in documents:
            groups.setdefault(
                (doc.get("MeetingType"), self._local_date(doc)), []
            ).append(doc)

        dropped = set()
        for (meeting_type, day), docs in groups.items():
            papered = [d for d in docs if _paper(d, "Agenda") or _paper(d, "Minutes")]
            if day is None or len(papered) != 2:
                continue
            agenda_only = [d for d in papered if not _paper(d, "Minutes")]
            minutes_only = [d for d in papered if not _paper(d, "Agenda")]
            if len(agenda_only) == 1 and len(minutes_only) == 1:
                keep, fold = agenda_only[0], minutes_only[0]
                if keep is fold:
                    continue
                self.logger.info(f"Joining the two {meeting_type} records of {day}")
                _put(keep, "Minutes", _take(fold, "Minutes"))
                dropped.add(id(fold))
        return [d for d in documents if id(d) not in dropped]

    def _check_agenda_slot(self, doc: dict) -> None:
        agenda = _paper(doc, "Agenda")
        if not agenda:
            return

        if is_minutes(agenda) and not _AGENDA_WORD.search(agenda):
            paper = _take(doc, "Agenda")
            if _paper(doc, "Minutes"):
                self.logger.info(f"Dropping {agenda!r}: minutes filed as the agenda")
            else:
                self.logger.info(f"Moving {agenda!r} from the agenda to the minutes")
                _put(doc, "Minutes", paper)
        elif is_not_an_agenda(agenda):
            _take(doc, "Agenda")
            self.logger.info(f"Dropping {agenda!r}: not the agenda")
        else:
            return

        # The slot is now empty, but the real agenda is often still on the
        # record: West Daly filed the minutes as the agenda of four meetings
        # and kept each one's agenda as a supporting document typed "Agenda".
        replacement = self._supporting_agenda(doc)
        if replacement:
            self.logger.info(f"Using {replacement['file']!r} as the agenda")
            _put(doc, "Agenda", replacement)

    def _supporting_agenda(self, doc: dict) -> Optional[dict]:
        """A supporting document that is this meeting's agenda, if any."""
        day = self._local_date(doc)
        for support in doc.get("SupportingDocuments") or []:
            name = support.get("DocumentFilePath") or ""
            kind = (support.get("WP_DocumentType") or {}).get("Name") or ""
            label = f"{kind} {support.get('Title') or ''} {name}"
            if not _AGENDA_WORD.search(label):
                continue
            if is_not_an_agenda(name) or is_minutes(name):
                continue
            named = filename_date(name)
            if named and named != day:
                continue
            if support.get("AssembledDocFolderName") and name:
                return _support_paper(support)
        return None

    def _check_minutes_slot(self, doc: dict) -> None:
        """Fill the minutes slot from the supporting documents.

        Councils sometimes attach the minutes to the record rather than
        uploading them as its minutes: Groote's 29 September 2025 meeting has
        an empty minutes slot and "... 29 September 2025 - Minutes.pdf" as a
        supporting document typed "Agenda", and Albury's 1 December 2025
        Community Forum report is a supporting document typed "Public Forum".
        Runs last, so a paper moved or joined into the slot by the other rules
        wins. Unconfirmed minutes also give way to a confirmed copy: West Daly
        kept "26 June 2025 - Minutes_unconfirmed.pdf" in the slot after
        attaching the confirmed minutes alongside it.
        """
        current = _paper(doc, "Minutes")
        if current and not _UNCONFIRMED.search(current):
            return
        replacement = self._supporting_minutes(doc, confirmed_only=bool(current))
        if replacement:
            if current:
                _take(doc, "Minutes")
            self.logger.info(
                f"Using {replacement['file']!r} as the minutes"
                + (f" in place of {current!r}" if current else "")
            )
            _put(doc, "Minutes", replacement)

    def _supporting_minutes(
        self, doc: dict, confirmed_only: bool = False
    ) -> Optional[dict]:
        """A supporting document that is this meeting's minutes, if any.

        Judged by the filename, not the document type, which councils set
        loosely (Groote typed its minutes "Agenda"). A filename naming another
        day is a previous meeting's minutes, attached for confirmation.
        Confirmed minutes are preferred to unconfirmed ones.
        """
        day = self._local_date(doc)
        found = []
        for support in doc.get("SupportingDocuments") or []:
            name = support.get("DocumentFilePath") or ""
            if not is_minutes(name) or is_not_an_agenda(name):
                continue
            named = filename_date(name)
            if named and named != day:
                continue
            if confirmed_only and _UNCONFIRMED.search(name):
                continue
            if support.get("AssembledDocFolderName"):
                found.append(_support_paper(support))
        found.sort(key=lambda paper: bool(_UNCONFIRMED.search(paper["file"])))
        return found[0] if found else None

    def _move_misfiled_papers(self, documents: list) -> None:
        by_type_and_day: dict[tuple, list[dict]] = {}
        for doc in documents:
            key = (doc.get("MeetingType"), self._local_date(doc))
            by_type_and_day.setdefault(key, []).append(doc)

        for doc in documents:
            day = self._local_date(doc)
            if day is None:
                continue
            for kind in ("Agenda", "Minutes"):
                name = _paper(doc, kind)
                named = filename_date(name)
                if named is None or named == day:
                    continue
                twins = by_type_and_day.get((doc.get("MeetingType"), named), [])
                if not twins:
                    continue  # the filename is as likely to be wrong
                empty = [t for t in twins if not _paper(t, kind)]
                if empty:
                    self.logger.info(
                        f"Moving {name!r} from the {day} record to {named}"
                    )
                    _put(empty[0], kind, _take(doc, kind))
                elif any(_same_paper(doc, twin, kind) for twin in twins):
                    self.logger.info(
                        f"Dropping {name!r} from the {day} record: it is a copy "
                        f"of the {named} meeting's"
                    )
                    _take(doc, kind)
                else:
                    # The other record has a different paper, so one of the
                    # two filenames is wrong and nothing here says which.
                    # Filenames are often copied from the last meeting's, so
                    # deleting this paper could delete this meeting's only
                    # agenda. The one copy seen live is byte-identical:
                    # Central Coast's 9 March 2021 record holds the 9
                    # November agenda, same name and 472,608 bytes on both.
                    self.logger.warning(
                        f"Leaving {name!r} on the {day} record: its filename "
                        f"names {named}, whose record holds a different paper"
                    )
                    continue
                if kind == "Agenda" and not _paper(doc, "Agenda"):
                    replacement = self._supporting_agenda(doc)
                    if replacement:
                        _put(doc, "Agenda", replacement)


def _paper(doc: dict, kind: str) -> Optional[str]:
    if doc.get(f"{kind}AssembledDocFolderName"):
        return doc.get(f"{kind}DocumentFilePath")
    return None


def _support_paper(support: dict) -> dict:
    return {
        "id": support.get("DocumentId"),
        "folder": support.get("AssembledDocFolderName"),
        "file": support.get("DocumentFilePath"),
        "size": support.get("SizeInBytes"),
    }


def _same_paper(doc: dict, other: dict, kind: str) -> bool:
    """The same upload on two records: same filename and same byte count.

    The two copies sit in different folders, so the folder cannot say this.
    """
    size = doc.get(f"{kind}SizeInBytes")
    return (
        bool(size)
        and _paper(doc, kind) == _paper(other, kind)
        and size == other.get(f"{kind}SizeInBytes")
    )


def _take(doc: dict, kind: str) -> dict:
    paper = {
        "id": doc.get(f"{kind}DocumentId"),
        "folder": doc.get(f"{kind}AssembledDocFolderName"),
        "file": doc.get(f"{kind}DocumentFilePath"),
        "size": doc.get(f"{kind}SizeInBytes"),
    }
    for field in ("DocumentId", "AssembledDocFolderName", "DocumentFilePath"):
        doc[f"{kind}{field}"] = None
    doc[f"{kind}SizeInBytes"] = None
    return paper


def _put(doc: dict, kind: str, paper: dict) -> None:
    doc[f"{kind}DocumentId"] = paper["id"]
    doc[f"{kind}AssembledDocFolderName"] = paper["folder"]
    doc[f"{kind}DocumentFilePath"] = paper["file"]
    doc[f"{kind}SizeInBytes"] = paper.get("size")
