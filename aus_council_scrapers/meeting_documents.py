"""Turn a list of individually-titled documents into meetings.

Some councils publish a flat register of documents rather than a list of
meetings: one row reads "Ordinary Council Meeting - Agenda - 13 October
2026", another "Ordinary Council Meeting - Minutes - 13 October 2026", and
nothing on the page says they belong together. Cockburn's whole register
looks like that, and so does Bayswater's before 2024. Emitting one record
per row would split every meeting in two—the failure the scorecard
reports as "split across agenda/minutes rows"—so the rows are grouped
here, by meeting date and by what the title says the meeting is.

The titles are typed by hand and drift, which is why grouping is not an
exact string match:

- the same committee is "Audit Risk and Compliance", "Audit, Risk and
  Compliance Committee Meeting" and "Minutes - Audit, Risk and Compliance
  Meeting" in one year;
- a committee renamed mid-cycle can have its agenda filed under the new name
  and its minutes under the old one ("Audit Risk and Improvement Committee -
  Agenda - 22 September 2026", "Audit Risk and Compliance Committee Meeting -
  Minutes - 22 September 2026");
- two special meetings on one evening differ only by start time ("(7pm)",
  "(7.30pm)").

So titles are reduced to a set of significant words, rows with the same
date, start time and word set are grouped, and then an agenda-only group and
a minutes-only group on the same date are joined when their word sets
largely overlap. Joining only complementary groups is what keeps two real
meetings on one night apart: if both already have an agenda, they are not
the same meeting however alike their names look.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Optional

from aus_council_scrapers.constants import TIME_REGEX

AGENDA = "agenda"
MINUTES = "minutes"

# Words that say nothing about which meeting a document belongs to. "Council"
# is here because "Ordinary Council Meeting" and "Ordinary Meeting of
# Council" are the same meeting; "ordinary" and "special" still tell those
# two apart.
_STOPWORDS = frozenset(
    {
        "a",
        "and",
        "agenda",
        "amended",
        "city",
        "committee",
        "confirmed",
        "council",
        "for",
        "meeting",
        "minutes",
        "of",
        "the",
        "unconfirmed",
    }
)

# Spellings of one body that share no words. Applied before splitting into
# words, so "Metro Inner-North JDAP" and "Joint Development Assessment
# Panel" both reduce to the same token.
_SYNONYMS = (
    (re.compile(r"\bm?i?j?dap\b|\b(?:joint )?development assessment panel\b"), " dap "),
    (re.compile(r"\bceo\b|\bchief executive officer\b"), " ceo "),
    (re.compile(r"\bagm\b|\bannual general\b"), " annual "),
)

_KIND_WORDS = re.compile(
    r"\b(?:(?:un)?confirmed\s+|amended\s+)?(?:agenda|minutes)(?:\s+(?:un)?confirmed)?\b",
    re.IGNORECASE,
)
_PANEL_NUMBER = re.compile(r"\b(?:M?I?J?DAP)/\d+\b|\bNo\.?\s*\d+\b", re.IGNORECASE)


@dataclass
class Document:
    kind: str  # AGENDA or MINUTES
    title: str  # meeting name as the council wrote it, date included or not
    date: datetime.date
    url: str
    # Lower is preferred when a meeting has more than one candidate for a
    # slot: an original agenda over an amended one, part 1 over part 2.
    rank: int = 0


@dataclass
class Meeting:
    date: datetime.date
    time: Optional[str]
    words: frozenset
    names: dict = field(default_factory=dict)  # kind -> title
    documents: dict = field(default_factory=dict)  # kind -> (rank, url)

    @property
    def name(self) -> str:
        # The agenda's title is the one written before the meeting, in the
        # council's own words for the meeting type; minutes titles more often
        # carry prefixes ("Minutes - ...") and confirmation notes.
        return self.names.get(AGENDA) or self.names.get(MINUTES)

    @property
    def agenda_url(self) -> Optional[str]:
        return self.documents.get(AGENDA, (None, None))[1]

    @property
    def minutes_url(self) -> Optional[str]:
        return self.documents.get(MINUTES, (None, None))[1]

    @property
    def stated_time(self) -> Optional[str]:
        """The start time, when the title says am or pm.

        The time also tells two meetings on one evening apart, so a bare
        "7.43" is still used for grouping; but it is not reported, because
        dateutil reads it as 7:43 in the morning. Dots become colons for the
        same reason: it reads "7.30pm" as 7 pm.
        """
        if not self.time or not re.search(r"[ap]\.?m", self.time, re.IGNORECASE):
            return None
        return self.time.replace(".", ":", 1)

    def complements(self, other: "Meeting") -> bool:
        return not (set(self.documents) & set(other.documents))


def meeting_time(title: str) -> Optional[str]:
    """A start time written into the title, such as "(7.30pm)"."""
    match = TIME_REGEX.search(title)
    return match.group().replace(" ", "") if match else None


def clean_name(title: str, date_pattern: re.Pattern) -> str:
    """The meeting type, with the date, document kind and panel number gone."""
    name = date_pattern.sub(" ", title)
    name = TIME_REGEX.sub(" ", name)
    name = _KIND_WORDS.sub(" ", name)
    name = _PANEL_NUMBER.sub(" ", name)
    name = re.sub(r"\(\s*\)", " ", name)
    # Rejoin what is left, dropping the segments that are now empty or say
    # only "Meeting" ("JDAP - Minutes - Meeting No. 289 - 14 December").
    # A dash with space on either side separates parts; an unspaced one is
    # part of a word ("Metro-Inner North", "COVID-19").
    segments = (
        re.sub(r"\s+", " ", s).strip(" ,-–—")
        for s in re.split(r"\s+[-–—]+\s*|\s*[-–—]+\s+", name)
    )
    return " - ".join(s for s in segments if s and s.lower() != "meeting")


def name_words(name: str) -> frozenset:
    text = name.lower()
    for pattern, replacement in _SYNONYMS:
        text = pattern.sub(replacement, text)
    words = set()
    for word in re.findall(r"[a-z0-9]+", text):
        if word in _STOPWORDS:
            continue
        # "Annual Elector Meeting" and "Annual Electors Meeting" are one
        # meeting; a crude plural strip is enough for meeting names.
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.add(word)
    # Development assessment panels are named by region and by the councils
    # sitting on them, in any combination ("Metro Inner-North JDAP", "JDAP
    # No. 25 City of Bayswater"). Only one panel sits for a council on a
    # given day, so being a panel is identity enough.
    if "dap" in words:
        return frozenset({"dap"})
    return frozenset(words)


def _similar(a: frozenset, b: frozenset) -> bool:
    if not a or not b:
        return a == b
    if a <= b or b <= a:
        return True
    return len(a & b) / len(a | b) >= 0.5


def group_documents(
    documents: list[Document], date_pattern: re.Pattern
) -> list[Meeting]:
    """Group documents into meetings, in the order each meeting first appears."""
    meetings: list[Meeting] = []
    by_key: dict[tuple, Meeting] = {}

    for doc in documents:
        name = clean_name(doc.title, date_pattern)
        time = meeting_time(doc.title)
        words = name_words(name)
        key = (doc.date, time, words)
        meeting = by_key.get(key)
        if meeting is None:
            meeting = Meeting(date=doc.date, time=time, words=words)
            by_key[key] = meeting
            meetings.append(meeting)

        current = meeting.documents.get(doc.kind)
        if current is None or doc.rank < current[0]:
            meeting.documents[doc.kind] = (doc.rank, doc.url)
            meeting.names[doc.kind] = name

    # Second pass: join an agenda-only group to a minutes-only group from the
    # same day when their names are close (see the module docstring).
    merged: list[Meeting] = []
    for meeting in meetings:
        partner = next(
            (
                m
                for m in merged
                if m.date == meeting.date
                and (m.time is None or meeting.time is None or m.time == meeting.time)
                and m.complements(meeting)
                and _similar(m.words, meeting.words)
            ),
            None,
        )
        if partner is None:
            merged.append(meeting)
            continue
        partner.documents.update(meeting.documents)
        for kind, name in meeting.names.items():
            partner.names.setdefault(kind, name)
        partner.time = partner.time or meeting.time

    return merged
