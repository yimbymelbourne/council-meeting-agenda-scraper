"""Rules the nine A-LGASA-3 councils add on top of `LGASAFunnelbackScraper`.

Each case is taken from the council's own listing, and each one, without its
rule, puts a document on the wrong meeting or invents a meeting that never
sat. The cassettes would re-record past any of that silently, so these pin
the rules through `scraper()`, the real entry point.
"""

import pytest

from aus_council_scrapers.scrapers.sa.goyder import GoyderScraper
from aus_council_scrapers.scrapers.sa.lower_eyre_peninsula import (
    LowerEyrePeninsulaScraper,
)
from aus_council_scrapers.scrapers.sa.northern_areas import NorthernAreasScraper
from aus_council_scrapers.scrapers.sa.roxby_downs import RoxbyDownsScraper
from aus_council_scrapers.scrapers.sa.tatiara import TatiaraScraper
from aus_council_scrapers.scrapers.sa.wakefield import WakefieldScraper
from aus_council_scrapers.scrapers.sa.yankalilla import YankalillaScraper
from aus_council_scrapers.scrapers.tas.kentish import KentishScraper
from tests.cassette import PlaybackFetcher
from tests.test_lgasa import as_listing_page, doc, url


def scrape(scraper_class, documents, years, panel=()):
    """Run `scraper()` with `documents` on the first listing page and
    `panel` on the second; any other listing page is empty."""
    scraper = scraper_class()
    scraper.years_filter = years
    pages = [documents, list(panel)]
    scraper.fetcher = PlaybackFetcher(
        [
            [
                ["selenium", scraper._page_url(listing)],
                as_listing_page(pages[i] if i < len(pages) else []),
            ]
            for i, listing in enumerate(scraper.listing_urls)
        ]
    )
    return [(r.date, r.name, r.agenda_url, r.minutes_url) for r in scraper.scraper()]


def test_tatiara_briefing_notes_and_confidential_items_are_not_meetings():
    label = "Council Agenda & Minutes"
    assert scrape(
        TatiaraScraper,
        [
            doc(
                "1978774",
                "2026-05-05",
                "2026 May 5 Council Briefing Session Notice",
                label,
            ),
            doc(
                "1985320",
                "2026-05-05",
                "2026 May 5 Council Briefing Session Notes",
                label,
            ),
            doc(
                "1058069",
                "2021-11-02",
                "2021 November 2 Informal Gathering Notes",
                label,
            ),
            doc("1836198", "2025-07-08", "2025 July 8 Council Agenda", label),
            doc(
                "1888672",
                "2025-07-08",
                "2025 July 8 Confidential Council Minutes - RFQ 39-24/25 Rubble "
                "Raising and Crushing",
                label,
            ),
            doc("1838911", "2025-07-07", "2025 July 8 Council Minutes", label),
        ],
        [2021, 2025, 2026],
    ) == [("2025-07-08", "Council Meeting", url("1836198"), url("1838911"))]


def test_tatiara_title_day_corrects_a_meeting_filed_on_the_wrong_day():
    label = "Council Agenda & Minutes"
    assert scrape(
        TatiaraScraper,
        [
            doc("1674019", "2024-09-06", "2024 September 10 Council Agenda", label),
            doc("1677746", "2024-09-06", "2024 September 10 Council Minutes", label),
            # A wrong year in the title is a typo, not a date to move to.
            doc(
                "1798514", "2025-04-22", "2022 April 22 Special Council Minutes", label
            ),
        ],
        [2024, 2025],
    ) == [
        ("2025-04-22", "Special Council Meeting", None, url("1798514")),
        ("2024-09-10", "Council Meeting", url("1674019"), url("1677746")),
    ]


def test_kentish_newsletter_and_information_evening_are_not_meetings():
    assert scrape(
        KentishScraper,
        [
            doc(
                "1301539",
                "2023-02-28",
                "At Council's Last Meeting - February 2023",
                "Full Council",
            ),
            doc(
                "1436325",
                "2023-07-20",
                "Agenda LG Reform Kentish CIE 20 July 2023",
                "Full Council",
            ),
            doc("1435709", "2023-07-18", "Agenda 18 July 2023", "Full Council"),
        ],
        [2023],
    ) == [("2023-07-18", "Council Meeting", url("1435709"), None)]


def test_roxby_downs_released_confidential_minutes_are_not_a_meeting():
    assert scrape(
        RoxbyDownsScraper,
        [
            doc(
                "1263088",
                "2022-12-21",
                "Council Meeting Notice and Agenda - 21 December 2022",
                "Council",
            ),
            doc(
                "1267297",
                "2022-12-21",
                "Council Meeting Minutes - 21 December 2022",
                "Council",
            ),
            doc(
                "1601282",
                "2022-12-22",
                "Confidential Minutes - Council - 21 December 2022 - Sports Precinct "
                "Tender Evaluation and Prudential Review - Released",
                "Council",
            ),
        ],
        [2022],
    ) == [("2022-12-21", "Council Meeting", url("1263088"), url("1267297"))]


@pytest.mark.parametrize(
    "scraper_class, label, documents, expected",
    [
        (
            YankalillaScraper,
            "Council Meetings",
            [
                (
                    "1159855",
                    "2022-06-10",
                    "Special Council Meeting Agenda - 10 June 2022",
                ),
                (
                    "1186301",
                    "2022-06-10",
                    "Special Council Meeting - 10 June 2022 - 5.1 Chief Executive "
                    "Officer Recruitment Minutes",
                ),
                ("1164111", "2022-06-17", "Special Council Minutes - 10 June 2022"),
            ],
            ("2022-06-10", "Special Council Meeting", "1159855", "1164111"),
        ),
        (
            NorthernAreasScraper,
            "Agenda and Minutes",
            [
                ("1483370", "2023-10-17", "Agenda - 17 October 2023"),
                ("1575133", "2023-10-17", "Released Minutes - 17 October 2023"),
                ("1486671", "2023-10-20", "Minutes - 17 October 2023"),
            ],
            ("2023-10-17", "Council Meeting", "1483370", "1486671"),
        ),
    ],
)
def test_full_minutes_filed_days_late_beat_the_stand_in_filed_on_the_day(
    scraper_class, label, documents, expected
):
    date, name, agenda, minutes = expected
    assert scrape(
        scraper_class,
        [doc(asset, filed, title, label) for asset, filed, title in documents],
        [int(date[:4])],
    ) == [(date, name, url(agenda), url(minutes))]


def test_goyder_two_digit_year_title_rejoins_minutes_filed_a_month_late():
    label = "Meetings of Council"
    assert scrape(
        GoyderScraper,
        [
            doc("1321991", "2023-04-18", "Agenda 18.04.2023", label),
            doc("1345092", "2023-05-18", "Minutes 18.04.23", label),
            # Two months from where it is filed: the title is the wrong one.
            doc(
                "1772383",
                "2025-03-04",
                "04.05.2025 Special Meeting Council Agenda Open",
                label,
            ),
            doc("1784622", "2025-03-04", "Confirmed Minutes Special 04.03.2025", label),
        ],
        [2023, 2025],
    ) == [
        ("2025-03-04", "Special Council Meeting", url("1772383"), url("1784622")),
        ("2023-04-18", "Council Meeting", url("1321991"), url("1345092")),
    ]


def test_lower_eyre_file_name_dates_a_month_only_title():
    homes = "Cummins Homes Committee"
    panel = "Eyre Peninsula Regional Assessment Panel (ERAP)"
    assert scrape(
        LowerEyrePeninsulaScraper,
        [
            # Filed on the upload day; the file and the agenda say the 9th.
            doc(
                "1288257",
                "2023-02-03",
                "Agenda - February 2023",
                homes,
                "CHC_20230209_AGN_29_AT.PDF",
            ),
            doc(
                "1292911",
                "2023-02-09",
                "Minutes - February 2023",
                homes,
                "CHC_20230209_MIN_29.PDF",
            ),
            # Filed a year early.
            doc(
                "1089640",
                "2021-01-18",
                "Agenda - January 2022",
                panel,
                "Agenda-Eyre-Regional-Assessment-Panel-18-January-2022.PDF",
            ),
            doc(
                "1095415", "2022-01-18", "Minutes - January 2022", panel, "Minutes.pdf"
            ),
            # Filed under 1 March with no day anywhere. Its front page says
            # 1 May, the committee's only meeting that month, which has an
            # agenda and no minutes: it joins that meeting.
            doc(
                "1802178",
                "2025-03-01",
                "Minutes - May 2025",
                homes,
                "Minutes-May-2025.pdf",
            ),
            doc(
                "1802181",
                "2025-05-01",
                "Agenda - May 2025",
                homes,
                "Agenda-May-2025.pdf",
            ),
            # Filed in March for April, when the committee met twice: which
            # meeting it belongs to cannot be told, so it is left out.
            doc("9000001", "2025-03-01", "Minutes - April 2025", homes),
            doc("9000002", "2025-04-03", "Agenda - April 2025", homes),
            doc("9000003", "2025-04-24", "Agenda - April 2025", homes),
        ],
        [2021, 2022, 2023, 2025],
    ) == [
        ("2025-05-01", homes, url("1802181"), url("1802178")),
        ("2025-04-24", homes, url("9000003"), None),
        ("2025-04-03", homes, url("9000002"), None),
        ("2023-02-09", homes, url("1288257"), url("1292911")),
        ("2022-01-18", panel, url("1089640"), url("1095415")),
    ]


def test_lower_eyre_redates_across_years_when_one_year_is_asked_for():
    """Production asks for one year. The panel agenda filed a year early has
    to reach the 2022 run without the 2021 one."""
    panel = "Eyre Peninsula Regional Assessment Panel (ERAP)"
    assert scrape(
        LowerEyrePeninsulaScraper,
        [
            doc(
                "1089640",
                "2021-01-18",
                "Agenda - January 2022",
                panel,
                "Agenda-Eyre-Regional-Assessment-Panel-18-January-2022.PDF",
            ),
            doc(
                "1095415", "2022-01-18", "Minutes - January 2022", panel, "Minutes.pdf"
            ),
        ],
        [2022],
    ) == [("2022-01-18", panel, url("1089640"), url("1095415"))]


def test_wakefield_panel_papers_are_dated_as_their_names_state():
    panel = "Mid North Regional Assessment Panel"
    assert scrape(
        WakefieldScraper,
        [],
        [2022, 2026],
        panel=[
            # Both filed under the 1 January placeholder of the next year.
            doc(
                "1421190",
                "2023-01-01",
                "15 December 2022 - Mid North Regional Assesment Panel Agenda",
                panel,
                "15-December-2022-Mid-North-Regional-Assesment-Panel-Agenda.pdf",
            ),
            doc(
                "1421195",
                "2023-01-01",
                "15 December 2022 - Mid North Regional Assesment Panel Minutes",
                panel,
                "15-December-2022-Mid-North-Regional-Assesment-Panel-Minutes.pdf",
            ),
            # The title's year is wrong; the file name and the front page
            # say 12 March 2026.
            doc(
                "1957751",
                "2026-01-01",
                "12 March 2025 - Mid North Regional Assesment Panel Minutes",
                panel,
                "Mid-North-Regional-Assessment-Panel-Minutes-12-March-2026.pdf",
            ),
        ],
    ) == [
        ("2026-03-12", panel, None, url("1957751")),
        ("2022-12-15", panel, url("1421190"), url("1421195")),
    ]


def test_yankalilla_panel_minutes_filed_a_month_early_rejoin_their_agenda():
    panel = "Fleurieu Regional Assessment Panel"
    assert scrape(
        YankalillaScraper,
        [],
        [2025],
        panel=[
            doc(
                "1840598",
                "2025-07-22",
                "FRAP Agenda - 22 July 2025",
                panel,
                "FRAP-Agenda-22-July-2025.pdf",
            ),
            doc(
                "1846163",
                "2025-07-22",
                "FRAP-Minutes-22-July-2025.pdf",
                panel,
                "FRAP-Minutes-22-July-2025.pdf",
            ),
            doc(
                "1856800",
                "2025-08-26",
                "FRAP-Agenda-26-August-2025.pdf",
                panel,
                "FRAP-Agenda-26-August-2025.pdf",
            ),
            doc(
                "1863184",
                "2025-07-26",
                "FRAP-Minutes-26-August-2025.pdf",
                panel,
                "FRAP-Minutes-26-August-2025.pdf",
            ),
        ],
    ) == [
        ("2025-08-26", panel, url("1856800"), url("1863184")),
        ("2025-07-22", panel, url("1840598"), url("1846163")),
    ]
