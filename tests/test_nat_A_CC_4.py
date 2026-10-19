"""The nine CouncilConnect shires of A-CC-4: production bound and corrections.

The production-bound checks are `test_councilconnect.py`'s own, run for
these nine. They belong in its COUNCILCONNECT_SCRAPERS list, which this
change does not edit; once the nine are added there, the first two tests
here can go.

Below them, the corrections ShireCouncilConnectScraper and the shire
modules make that fixture replay pins down only in passing, or not at all:
a placeholder time coming back from an upcoming page's button (no upcoming
meeting in the cassettes has one), a module's default time, and the
document choices that depend on the order links are listed in.
"""

import datetime

import pytest

from aus_council_scrapers.scrapers.wa.gnowangerup import GnowangerupScraper
from aus_council_scrapers.scrapers.wa.jerramungup import JerramungupScraper
from aus_council_scrapers.scrapers.wa.kellerberrin import KellerberrinScraper
from aus_council_scrapers.scrapers.wa.lake_grace import LakeGraceScraper
from tests import test_councilconnect

A_CC_4_SCRAPERS = [
    "WonganBalliduScraper",
    "LakeGraceScraper",
    "CunderdinScraper",
    "GnowangerupScraper",
    "MeekatharraScraper",
    "JerramungupScraper",
    "KellerberrinScraper",
    "BroomehillTambellupScraper",
    "PingellyScraper",
]


@pytest.mark.parametrize("class_name", A_CC_4_SCRAPERS)
def test_one_year_fetches_only_that_year_and_loses_nothing(class_name):
    test_councilconnect.test_one_year_fetches_only_that_year_and_loses_nothing(
        class_name
    )


@pytest.mark.parametrize("class_name", A_CC_4_SCRAPERS)
def test_document_urls_carry_no_file_store_version(class_name):
    test_councilconnect.test_document_urls_carry_no_file_store_version(class_name)


class _Pages:
    """A fetcher serving fixed HTML by URL."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def fetch_with_requests(self, url, method="GET", **kwargs):
        return self.pages[url]


def _meeting_page(when: str, documents: list[tuple[str, str, str]]) -> str:
    """A meeting page as CouncilConnect writes it: `documents` are
    (group, label, filename) in the order the page lists them."""
    body = ""
    group = None
    for heading, label, filename in documents:
        if heading != group:
            body += f"<h3>{heading}</h3>"
            group = heading
        body += f'<a href="documents/{filename}" title="View {label}">{label}</a>'
    return (
        '<div class="meeting-info"><h1>Ordinary Council Meeting</h1>'
        f"<h2>{when}</h2></div>"
        f'<div class="meeting-documents">{body}</div>'
    )


def _read(scraper, url: str, page: str, fallback=None):
    scraper.fetcher = _Pages({url: page})
    return scraper._meeting_from_detail(url, {}, fallback)


LAKE_GRACE_PAGE = (
    "https://www.lakegrace.wa.gov.au/council-meetings/ordinary-council-meeting"
    "/ordinary-council-meeting-28-october-2026/900/"
)
AN_AGENDA = [("Agenda", "Agenda", "agenda.pdf")]


@pytest.mark.parametrize(
    "when, button_time, expected",
    [
        # Dropped from the page, and not put back from the button.
        ("Wednesday, October 28, 2026 - 12:00 AM", "12:00 AM", None),
        ("Wednesday, October 28, 2026 - 3:30 AM", "3:30 AM", None),
        # The button's time is still used where it is believable.
        ("Wednesday, October 28, 2026 - 12:00 AM", "3:30 PM", "3:30 PM"),
        ("Wednesday, October 28, 2026", "3:30 PM", "3:30 PM"),
        # A believable page time is kept whatever the button says.
        ("Wednesday, October 28, 2026 - 3:30 PM", "12:00 AM", "3:30 PM"),
    ],
)
def test_placeholder_time_is_dropped_on_the_upcoming_path_too(
    when, button_time, expected
):
    meeting = _read(
        LakeGraceScraper(),
        LAKE_GRACE_PAGE,
        _meeting_page(when, AN_AGENDA),
        (datetime.date(2026, 10, 28), button_time),
    )
    assert meeting.date == "2026-10-28"
    assert meeting.time == expected


@pytest.mark.parametrize(
    "when, expected",
    [
        # The module's default before May 2025 (the agenda says 4 pm).
        ("Tuesday, June 20, 2023 - 6:00 PM", None),
        # After it, a 6 pm time is the meeting's, as is any other time.
        ("Tuesday, May 19, 2026 - 6:00 PM", "6:00 PM"),
        ("Tuesday, June 20, 2023 - 4:00 PM", "4:00 PM"),
    ],
)
def test_module_default_time_is_dropped_before_the_cut_over(when, expected):
    url = (
        "https://www.kellerberrin.wa.gov.au/council-meetings"
        "/ordinary-council-meeting/ordinary-council-meeting/19/"
    )
    meeting = _read(KellerberrinScraper(), url, _meeting_page(when, AN_AGENDA))
    assert meeting.time == expected


def test_gnowangerup_agenda_report_is_not_taken_for_the_agenda():
    # 25 March 2020: every file is "-attachmentN", and "Agenda Report" (the
    # LEMC minutes attached to Report 11.2) is listed before the agenda.
    url = (
        "https://www.gnowangerup.wa.gov.au/council-meetings"
        "/ordinary-council-meeting/ordinary-council-meeting/46/"
    )
    page = _meeting_page(
        "Wednesday, March 25, 2020 - 3:30 PM",
        [
            ("Minutes", "Minutes Unconfirmed", "25032020-attachment1.pdf"),
            ("Minutes", "Minutes", "25032020.pdf"),
            ("Agenda", "Agenda Report", "25032020-attachment2.pdf"),
            ("Agenda", "Agenda", "25032020-attachment3.pdf"),
        ],
    )
    meeting = _read(GnowangerupScraper(), url, page)
    assert meeting.agenda_url == f"{url}documents/25032020-attachment3.pdf"
    assert meeting.minutes_url == f"{url}documents/25032020.pdf"


JERRAMUNGUP_PAGE = (
    "https://www.jerramungup.wa.gov.au/council-meetings/ordinary-council-meeting"
    "/25-october-2023/349/"
)


@pytest.mark.parametrize("special_first", [False, True])
def test_jerramungup_ordinary_papers_do_not_depend_on_link_order(special_first):
    # 25 October 2023: a Special meeting's papers filed on the Ordinary
    # meeting's page, under the same headings. They are kept for a record of
    # their own, so the Ordinary record gets the OCM papers however the page
    # orders them.
    minutes = [
        ("Minutes", "OCM Minutes - 25 October 2023", "ocm-minutes.pdf"),
        ("Minutes", "SCM Minutes - 25 October 2023", "scm-minutes.pdf"),
    ]
    agendas = [
        ("Agenda", "OCM Agenda - 25 October 2023", "ocm-agenda.pdf"),
        ("Agenda", "SCM Agenda - 25 October 2023", "scm-agenda.pdf"),
    ]
    if special_first:
        minutes.reverse()
        agendas.reverse()
    scraper = JerramungupScraper()
    meeting = _read(
        scraper,
        JERRAMUNGUP_PAGE,
        _meeting_page("Wednesday, October 25, 2023 - 02:00 PM", minutes + agendas),
    )
    assert meeting.agenda_url == f"{JERRAMUNGUP_PAGE}documents/ocm-agenda.pdf"
    assert meeting.minutes_url == f"{JERRAMUNGUP_PAGE}documents/ocm-minutes.pdf"
    assert sorted(
        url.rsplit("/", 1)[-1]
        for _, _, url in scraper._special_papers[JERRAMUNGUP_PAGE]
    ) == ["scm-agenda.pdf", "scm-minutes.pdf"]


def test_jerramungup_numbered_special_minutes_in_a_report_are_not_split_out():
    # "10.2 a) SCM Minutes - 7 August 2026" among 1 September 2026's reports
    # is a report, not a Special meeting held on that page.
    url = (
        "https://www.jerramungup.wa.gov.au/council-meetings"
        "/ordinary-council-meeting/1-september-2026/383/"
    )
    page = _meeting_page(
        "Tuesday, September 1, 2026 - 01:00 PM",
        [
            ("Documents", "10.2 a) SCM Minutes - 7 August 2026", "102-a.pdf"),
            ("Minutes", "1 September 2026 Minutes", "minutes.pdf"),
            ("Agenda", "1 September 2026 Agenda", "agenda.pdf"),
        ],
    )
    scraper = JerramungupScraper()
    meeting = _read(scraper, url, page)
    assert meeting.agenda_url == f"{url}documents/agenda.pdf"
    assert scraper._special_papers == {}
