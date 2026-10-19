"""Tests for how `MooneeValleyScraper` reads its hand-edited 2018–2025 archive.

The cassette shows today's page; these pin the two rules that keep a wrong
link off a meeting when the editors next add an attachment or misdate a row.
"""

from bs4 import BeautifulSoup

from aus_council_scrapers.scrapers.vic.moonee_valley import MooneeValleyScraper

UPLOADS = "https://mvcc.vic.gov.au/wp-content/uploads/2024/09/"


def _meetings(date_cell: str, agenda_cell: str, minutes_cell: str):
    table = BeautifulSoup(
        f"<table><tr><td>{date_cell}</td><td>{agenda_cell}</td>"
        f"<td>{minutes_cell}</td></tr></table>",
        "html.parser",
    ).table
    return MooneeValleyScraper()._parse_table(table, 2024, True, None)


def _link(label: str, filename: str) -> str:
    return f'<a href="{UPLOADS}{filename}">{label}</a>'


def test_a_labelled_link_beats_an_attachment_named_minutes():
    """An undated attachment whose filename says "Minutes", after the real
    minutes, must not replace them."""
    (meeting,) = _meetings(
        "Planning Delegated Committee - Tuesday 10 September 6.30pm",
        _link("Agenda", "Agenda-388KB.pdf"),
        _link("Minutes", "Minutes-388KB.pdf")
        + _link("Audit and Risk Committee", "Audit-Committee-Confirmed-Minutes.pdf"),
    )

    assert meeting.minutes_url == UPLOADS + "Minutes-388KB.pdf"


def test_a_misdated_row_goes_on_the_day_its_papers_agree_on():
    (meeting,) = _meetings(
        "Place Naming Delegated Committee - Tuesday 16 March 2021 4.45pm",
        _link("Agenda", "Agenda-23-March-2021.pdf"),
        _link("Minutes", "Minutes-23-March-2021.pdf"),
    )

    assert meeting.date == "2021-03-23"
    assert meeting.minutes_url == UPLOADS + "Minutes-23-March-2021.pdf"


def test_one_misfiled_paper_does_not_move_the_meeting():
    """26 March 2019's agenda link is the 12 March agenda; its minutes are
    its own. The agenda is dropped and the meeting stays on its day."""
    (meeting,) = _meetings(
        "Tuesday 26 March 6.30pm",
        _link("Agenda", "Agenda-12-March-2019.pdf"),
        _link("Minutes", "Minutes-26-March-2019.pdf"),
    )

    assert meeting.date == "2024-03-26"
    assert meeting.agenda_url is None
