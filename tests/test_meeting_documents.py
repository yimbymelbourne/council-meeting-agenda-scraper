"""Grouping per-document register rows into meetings.

The cassettes for cockburn and bayswater show what the grouping produced on
the day they were recorded, but a re-record accepts whatever it produces
next. These pin the two ways it can go wrong: joining two real meetings, and
leaving one meeting split across an agenda row and a minutes row.
"""

import datetime

import pytest

from aus_council_scrapers.constants import DATE_REGEX
from aus_council_scrapers.meeting_documents import (
    AGENDA,
    MINUTES,
    Document,
    group_documents,
)

DAY = datetime.date(2026, 9, 22)


def _doc(kind, title, url, date=DAY, rank=0):
    return Document(kind=kind, title=title, date=date, url=url, rank=rank)


def _shape(meetings):
    return sorted(((m.name, m.agenda_url, m.minutes_url) for m in meetings), key=str)


@pytest.mark.parametrize(
    "documents, expected",
    [
        pytest.param(
            [
                _doc(
                    AGENDA,
                    "Audit Risk and Improvement Committee - Agenda - 22 September 2026",
                    "a",
                ),
                _doc(
                    MINUTES,
                    "Audit Risk and Compliance Committee Meeting - Minutes - 22 September 2026",
                    "m",
                ),
            ],
            [("Audit Risk and Improvement Committee", "a", "m")],
            id="committee renamed between agenda and minutes",
        ),
        pytest.param(
            [
                _doc(
                    MINUTES,
                    "Minutes - Audit, Risk and Compliance Meeting -22 September 2026 - City of Cockburn",
                    "m",
                ),
                _doc(
                    AGENDA,
                    "Audit Risk and Compliance - Agenda - 22 September 2026",
                    "a",
                ),
            ],
            [("Audit Risk and Compliance", "a", "m")],
            id="prefix and suffix noise around the same name",
        ),
        pytest.param(
            [
                _doc(
                    AGENDA,
                    "Metro Inner-North Joint Development Assessment Panel Meeting 22 September 2026 - Agenda",
                    "a",
                ),
                _doc(
                    MINUTES,
                    "JDAP No. 25 City of Bayswater Meeting 22 September 2026 - Minutes",
                    "m",
                ),
            ],
            [
                (
                    "Metro Inner-North Joint Development Assessment Panel Meeting",
                    "a",
                    "m",
                )
            ],
            id="panel named two unrelated ways",
        ),
        pytest.param(
            [
                _doc(
                    AGENDA,
                    "Special Council Meeting - Agenda - 22 September 2026 (7pm)",
                    "a1",
                ),
                _doc(
                    AGENDA,
                    "Special Council Meeting - Agenda - 22 September 2026 (7.30pm)",
                    "a2",
                ),
                _doc(
                    MINUTES,
                    "Special Council Meeting - Minutes - 22 September 2026 (7.30pm)",
                    "m2",
                ),
                _doc(
                    MINUTES,
                    "Special Council Meeting - Minutes - 22 September 2026 (7pm)",
                    "m1",
                ),
            ],
            [
                ("Special Council Meeting", "a1", "m1"),
                ("Special Council Meeting", "a2", "m2"),
            ],
            id="two meetings one evening apart by start time",
        ),
        pytest.param(
            [
                _doc(
                    AGENDA,
                    "Aged Care Governance Committee - Agenda - 22 September 2026",
                    "ga",
                ),
                _doc(
                    AGENDA,
                    "Aged Care Asset Divestment Committee - Agenda - 22 September 2026",
                    "da",
                ),
                _doc(
                    MINUTES,
                    "Aged Care Governance Committee - Minutes - 22 September 2026",
                    "gm",
                ),
                _doc(
                    MINUTES,
                    "Aged Care Asset Divestment Committee - Minutes - 22 September 2026",
                    "dm",
                ),
            ],
            [
                ("Aged Care Asset Divestment Committee", "da", "dm"),
                ("Aged Care Governance Committee", "ga", "gm"),
            ],
            id="similar committees on one day stay apart",
        ),
        pytest.param(
            [
                _doc(
                    AGENDA,
                    "Ordinary Council Meeting - Amended Agenda - 22 September 2026",
                    "amended",
                    rank=1,
                ),
                _doc(
                    AGENDA,
                    "Ordinary Council Meeting - Agenda - 22 September 2026",
                    "original",
                ),
            ],
            [("Ordinary Council Meeting", "original", None)],
            id="original agenda preferred over amended",
        ),
        pytest.param(
            [
                _doc(
                    AGENDA, "Ordinary Council Meeting - Agenda - 22 September 2026", "a"
                ),
                _doc(
                    MINUTES,
                    "Ordinary Council Meeting - Minutes - 29 September 2026",
                    "m",
                    date=datetime.date(2026, 9, 29),
                ),
            ],
            [
                ("Ordinary Council Meeting", "a", None),
                ("Ordinary Council Meeting", None, "m"),
            ],
            id="different dates never join",
        ),
    ],
)
def test_group_documents(documents, expected):
    assert _shape(group_documents(documents, DATE_REGEX)) == expected
