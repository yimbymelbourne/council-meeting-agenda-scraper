"""Tests for `TitleCorrectedLGASAScraper`, the title-led corrections used by
Coober Pedy, Wudinna, Kimba, Elliston, Karoonda East Murray and Orroroo
Carrieton.

Each case is a real listing entry from one of those councils, where the
base class's grouping on committee and filed date put the wrong paper on a
meeting or split one meeting in two. They drive `scraper()` through a
playback fetcher, as `tests/test_lgasa.py` does, so a re-record cannot
quietly undo one.
"""

import re

import pytest

from aus_council_scrapers.scrapers.sa._lgasa_titles import TitleCorrectedLGASAScraper
from tests.cassette import PlaybackFetcher, encode_failure
from tests.test_lgasa import LISTING, as_listing_page, doc, url

PANEL = "https://www.example.sa.gov.au/assessment-panel"


class _Scraper(TitleCorrectedLGASAScraper):
    listing_urls = (LISTING,)
    title_bodies = (
        (re.compile(r"\bworkshop\b", re.IGNORECASE), "Council Workshop"),
        (re.compile(r"\baudit committee\b", re.IGNORECASE), None),
    )

    def __init__(self):
        super().__init__("example_sa", "SA", "https://www.example.sa.gov.au")


def scrape(results, year):
    scraper = _Scraper()
    scraper.years_filter = [year]
    page = scraper._page_url(LISTING)
    scraper.fetcher = PlaybackFetcher([[["selenium", page], as_listing_page(results)]])
    return [(r.date, r.name, r.agenda_url, r.minutes_url) for r in scraper.scraper()]


def test_a_workshop_filed_beside_a_council_meeting_is_its_own_meeting():
    # Kimba, 9 April 2025: the workshop's papers have the lower asset ids,
    # and grouped with the meeting they were chosen as the meeting's.
    results = [
        doc("1789782", "2025-04-09", "Council Meeting Agenda 9th April 2025"),
        doc("1788341", "2025-04-09", "Council Workshop Agenda 9th April 2025"),
        doc("1794669", "2025-04-09", "Council Workshop Minutes 9th April 2025"),
        doc("1794667", "2025-04-09", "Council Meeting Minutes 9th April 2025"),
    ]
    assert scrape(results, 2025) == [
        ("2025-04-09", "Council Workshop", url("1788341"), url("1794669")),
        ("2025-04-09", "Council Meeting", url("1789782"), url("1794667")),
    ]


def test_a_title_body_of_none_drops_the_document():
    # Elliston filed a released confidential Audit Committee item under the
    # council label; it is neither a council meeting nor that committee's
    # minutes.
    results = [
        doc(
            "1487585",
            "2020-06-05",
            "Released Confidential Audit Committee Meeting Minutes - 5 June 2020",
        ),
        doc("688711", "2020-06-16", "Ordinary Council Meeting Agenda - 16 June 2020"),
    ]
    assert scrape(results, 2020) == [
        ("2020-06-16", "Council Meeting", url("688711"), None)
    ]


def test_papers_titled_plus_attachments_are_the_papers_but_attachments_are_not():
    # Coober Pedy, 2022-23: the whole agenda and minutes were "+ attachments";
    # the separately uploaded "- Attachment 1" is still an attachment.
    results = [
        doc("1259925", "2022-12-13", "Agenda 13 December 2022 + attachments"),
        doc("1265653", "2022-12-13", "Minutes 13 December 2022 + attachments"),
        doc("1078149", "2022-12-13", "Minutes 13 December 2022 - Attachment 1"),
    ]
    assert scrape(results, 2022) == [
        ("2022-12-13", "Council Meeting", url("1259925"), url("1265653"))
    ]


@pytest.mark.parametrize(
    "results, year, expected",
    [
        pytest.param(
            # Coober Pedy: the June agenda filed a month late.
            [
                doc(
                    "1600001",
                    "2024-07-26",
                    "Agenda for the Ordinary Meeting of Council - 26 June 2024",
                ),
                doc(
                    "1600002",
                    "2024-06-26",
                    "Minutes of Ordinary Meeting of Council - 26 June 2024",
                ),
            ],
            2024,
            [("2024-06-26", "Council Meeting", url("1600001"), url("1600002"))],
            id="a-month-slip-in-a-full-dated-title",
        ),
        pytest.param(
            # Coober Pedy, 27 August 2025: both papers filed under the 28th.
            [
                doc(
                    "1858001",
                    "2025-08-28",
                    "Agenda of Ordinary Meeting of Council 27 August 2025",
                ),
                doc(
                    "1858002",
                    "2025-08-28",
                    "Minutes of Ordinary Meeting of Council 27 August 2025",
                ),
            ],
            2025,
            [("2025-08-27", "Council Meeting", url("1858001"), url("1858002"))],
            id="both-papers-filed-a-day-out",
        ),
        pytest.param(
            # Wudinna: "August 2020 Agenda" filed under 18 July.
            [
                doc("700001", "2020-07-18", "August 2020 Agenda"),
                doc("700002", "2020-08-18", "August 2020 Minutes"),
                doc("700003", "2020-07-21", "July 2020 Agenda"),
                doc("700004", "2020-07-21", "July 2020 Minutes"),
            ],
            2020,
            [
                ("2020-08-18", "Council Meeting", url("700001"), url("700002")),
                ("2020-07-21", "Council Meeting", url("700003"), url("700004")),
            ],
            id="a-month-only-title-onto-that-months-one-meeting",
        ),
        pytest.param(
            # Wudinna: the agenda filed under its notice date, 12 February;
            # the PDF calls the meeting for the 18th.
            [
                doc("1761001", "2025-02-12", "February 2025 Agenda"),
                doc("1767021", "2025-02-18", "February 2025 Minutes"),
            ],
            2025,
            [("2025-02-18", "Council Meeting", url("1761001"), url("1767021"))],
            id="an-agenda-filed-under-its-notice-date",
        ),
        pytest.param(
            # Orroroo Carrieton: the 2026 agenda titled 2025. A year out is
            # the title's typo, not a filing slip, so the date stands.
            [
                doc("1956537", "2026-03-25", "Council Meeting Agenda 25 March 2025"),
                doc("1958665", "2026-03-25", "Council Meeting Minutes 25 March 2026"),
            ],
            2026,
            [("2026-03-25", "Council Meeting", url("1956537"), url("1958665"))],
            id="a-year-typo-in-the-title-moves-nothing",
        ),
    ],
)
def test_a_misfiled_meeting_date_is_corrected_from_the_titles(results, year, expected):
    assert scrape(results, year) == expected


def test_minutes_titled_for_another_month_rank_behind_the_meetings_own():
    # Orroroo Carrieton, 25 January 2023: December's minutes, from a meeting
    # held that day, have the lower asset id.
    results = [
        doc("1281850", "2023-01-25", "Council Meeting Agenda 25 January 2023"),
        doc("1284704", "2023-01-25", "Council Meeting Minutes 25 January 2023"),
        doc(
            "1284702",
            "2023-01-25",
            "Council Meeting Minutes December 2022 (held 25 Jan 2023)",
        ),
    ]
    assert scrape(results, 2023) == [
        ("2023-01-25", "Council Meeting", url("1281850"), url("1284704"))
    ]


def test_a_listing_entry_with_no_file_is_never_a_meetings_paper():
    # Wudinna, 15 December 2020: "December 2020 Agenda" is listed with no
    # file and ?a=818422 serves 0 bytes; it was the meeting's only agenda.
    results = [
        doc("818422", "2020-12-15", "December 2020 Agenda", filename=None),
        doc("818347", "2020-12-15", "December 2020 Minutes"),
    ]
    assert scrape(results, 2020) == [
        ("2020-12-15", "Council Meeting", None, url("818347"))
    ]


@pytest.mark.parametrize(
    "original, revision",
    [
        # Orroroo Carrieton: the updated agenda has seven more pages.
        (
            "Council Meeting Agenda 22 April 2026",
            "Council Meeting Agenda 22 April 2026 *Updated*",
        ),
        # Coober Pedy; "amended" alone is a weaker mark in the base class.
        ("Agenda 28 February 2026", "Agenda 28 February 2026 - amended"),
    ],
)
def test_a_re_upload_marked_updated_or_amended_replaces_the_original(
    original, revision
):
    date = "2026-04-22" if "April" in original else "2026-02-28"
    results = [
        doc("1969440", date, original),
        doc("1971776", date, revision),
        doc("1973715", date, original.replace("Agenda", "Minutes")),
    ]
    assert scrape(results, 2026) == [
        (date, "Council Meeting", url("1971776"), url("1973715"))
    ]


def test_an_amended_attachment_does_not_replace_the_agenda():
    # Coober Pedy filed "Agenda 25 October 2023 - Amended Attachment Item
    # 13.6" beside that agenda. Attachments are excluded anyway; an amended
    # single item is not, and it is not a revision of the agenda either.
    results = [
        doc("1480001", "2023-10-25", "Agenda 25 October 2023"),
        doc("1488223", "2023-10-25", "Agenda 25 October 2023 - Amended Item 13.6"),
    ]
    assert scrape(results, 2023) == [
        ("2023-10-25", "Council Meeting", url("1480001"), None)
    ]


class _TwoListings(_Scraper):
    listing_urls = (LISTING, PANEL)


def test_losing_one_of_two_listings_fails_the_run():
    # Kimba, Elliston and Karoonda East Murray read the council's page and
    # the panel's. The base class only raises when both fail; with the
    # council's page lost, a run would report only the panel's meetings.
    scraper = _TwoListings()
    scraper.years_filter = [2026]
    panel = [doc("2000001", "2026-09-14", "EPRAP Agenda 14 September 2026")]
    scraper.fetcher = PlaybackFetcher(
        [
            [
                ["selenium", scraper._page_url(LISTING)],
                encode_failure(TimeoutError("challenge did not clear")),
            ],
            [["selenium", scraper._page_url(PANEL)], as_listing_page(panel)],
        ]
    )
    with pytest.raises(RuntimeError, match="agendas-and-minutes"):
        scraper.scraper()
