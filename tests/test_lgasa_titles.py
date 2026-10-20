"""The title rules of the small LGA SA councils (`lgasa_titles`).

The cassettes prove these councils work end to end, but a re-record accepts
any change in which document becomes "the agenda". These pin each rule
against the council it was written for, with listings shaped like the real
papers that broke the base class. Each case failed on plain
`LGASAFunnelbackScraper`: the recorded diffs are in the commit that added
the rule.
"""

import pytest

from aus_council_scrapers.scrapers.sa.barunga_west import BarungaWestScraper
from aus_council_scrapers.scrapers.sa.flinders_ranges import FlindersRangesScraper
from aus_council_scrapers.scrapers.sa.mount_remarkable import MountRemarkableScraper
from aus_council_scrapers.scrapers.sa.southern_mallee import SouthernMalleeScraper
from aus_council_scrapers.scrapers.sa.streaky_bay import StreakyBayScraper
from aus_council_scrapers.scrapers.sa.tumby_bay import TumbyBayScraper
from tests.cassette import PlaybackFetcher, encode_failure
from tests.test_lgasa import as_listing_page, doc, url


def scrape(scraper_class, documents, year):
    """Run a council's scraper over one synthetic page of its first listing."""
    scraper = scraper_class()
    scraper.listing_urls = scraper.listing_urls[:1]
    scraper.years_filter = [year]
    page = scraper._page_url(scraper.listing_urls[0])
    scraper.fetcher = PlaybackFetcher(
        [[["selenium", page], as_listing_page(documents)]]
    )
    return [(r.date, r.name, r.agenda_url, r.minutes_url) for r in scraper.scraper()]


def test_a_briefing_session_filed_as_council_papers_is_not_a_council_meeting():
    council = "Agenda and Minutes"
    assert scrape(
        TumbyBayScraper,
        [
            doc(
                1,
                "2026-01-20",
                "Ordinary Council Meeting Agenda - 20th January 2026",
                council,
            ),
            doc(
                2,
                "2026-01-20",
                "Ordinary Council Meeting Minutes - 20th January 2026",
                council,
            ),
            doc(
                3,
                "2026-01-27",
                "Information Briefing Session - 27 January 2026",
                council,
                filename="Information-Briefing-Session-27-January-2026-Agenda.pdf",
            ),
        ],
        2026,
    ) == [("2026-01-20", "Council Meeting", url(1), url(2))]


def test_another_bodys_papers_filed_as_council_papers_go_to_that_body():
    # Barunga West's 24 March 2020 executive committee minutes had become
    # the minutes of that day's special council meeting.
    council = "Council Agenda & Minutes"
    assert scrape(
        BarungaWestScraper,
        [
            doc(
                1,
                "2020-03-24",
                "24 March 2020 Special Meeting of Council Agenda",
                council,
            ),
            doc(
                2,
                "2020-03-24",
                "March 24 2020 Executive Committee Meeting Minutes",
                council,
            ),
            doc(
                3,
                "2020-03-24",
                "March 24 2020 Special Meeting of Council Minutes",
                council,
            ),
        ],
        2020,
    ) == [
        ("2020-03-24", "Special Council Meeting", url(1), url(3)),
        ("2020-03-24", "Executive Committee", None, url(2)),
    ]


def test_a_paper_filed_a_month_off_is_grouped_under_its_titles_date():
    council = "Council Agenda & Minutes"
    assert scrape(
        BarungaWestScraper,
        [
            doc(
                1, "2021-02-09", "Feb 09 2021 Ordinary Council Meeting Agenda", council
            ),
            doc(
                2, "2021-01-09", "Feb 09 2021 Ordinary Council Meeting Minutes", council
            ),
        ],
        2021,
    ) == [("2021-02-09", "Council Meeting", url(1), url(2))]


def test_a_paper_whose_file_name_gives_the_filed_date_stays_on_it():
    # The title's date is four weeks off, but the uploaded file's name gives
    # the filed date, so the filed date stands.
    assert scrape(
        BarungaWestScraper,
        [
            doc(
                1,
                "2020-11-09",
                "October 12 2020 Audit Committee Special Meeting Minutes",
                "Council Agenda & Minutes",
                filename="3.-November-09-2020-Audit-Committee-Special-Meeting.pdf",
            )
        ],
        2020,
    ) == [("2020-11-09", "Special Audit Committee", None, url(1))]


def test_the_full_agenda_papers_are_the_agenda_not_the_order_of_business():
    label = "Ordinary & Special Meetings of Council"
    full = "FRC Agenda 15 September 2026 - Agenda, Reports & Attachments"
    assert scrape(
        FlindersRangesScraper,
        [
            doc(1, "2026-09-15", "FRC Agenda 15 September 2026 - Agenda Only", label),
            doc(2, "2026-09-15", full, label),
            doc(
                3, "2026-07-08", "FRC Special Agenda 08 July 2026 - Agenda Only", label
            ),
        ],
        2026,
    ) == [
        ("2026-09-15", "Council Meeting", url(2), None),
        # No full papers were filed, so the order of business stands in.
        ("2026-07-08", "Special Council Meeting", url(3), None),
    ]


def test_an_ordinary_and_a_special_meeting_on_one_day_are_two_meetings():
    label = "Council Agendas and Minutes"
    assert scrape(
        SouthernMalleeScraper,
        [
            doc(
                1,
                "2024-09-18",
                "Notice of Council Meeting and Agenda 18 September 2024",
                label,
            ),
            doc(
                2,
                "2024-09-18",
                "Notice of Special Council Meeting and Agenda 18 September 2024",
                label,
            ),
            doc(3, "2024-09-18", "Council Meeting Minutes 18 September 2024", label),
            doc(
                4,
                "2024-09-18",
                "Special Council Meeting Minutes 18 September 2024",
                label,
            ),
        ],
        2024,
    ) == [
        ("2024-09-18", "Special Council Meeting", url(2), url(4)),
        ("2024-09-18", "Council Meeting", url(1), url(3)),
    ]


def test_two_numbered_special_meetings_on_one_day_keep_their_own_papers():
    # Mount Remarkable's 6 July 2021: the base class paired #1's agenda with
    # #2's minutes.
    label = "Council Agenda and Minutes"
    meetings = scrape(
        MountRemarkableScraper,
        [
            doc(
                1, "2021-07-06", "Agenda 6 July 2021 Special Council Meeting #1", label
            ),
            doc(
                2, "2021-07-06", "Agenda 6 July 2021 Special Council Meeting #2", label
            ),
            doc(
                3,
                "2021-07-06",
                "Minutes 6 July 2021 Special Council Meeting # 2",
                label,
            ),
            doc(
                4, "2021-07-06", "Minutes 6 July 2021 Special Council Meeting #1", label
            ),
        ],
        2021,
    )
    assert sorted((agenda, minutes) for _, _, agenda, minutes in meetings) == [
        (url(1), url(4)),
        (url(2), url(3)),
    ]


def test_minutes_re_released_in_full_replace_the_first_version():
    # Barunga West's 28 April 2023 special meeting, emitted twice: the
    # extra words of the re-released papers read as a second sitting. The
    # "agenda" re-released with them is a copy of the minutes.
    council = "Council Agenda & Minutes"
    assert scrape(
        BarungaWestScraper,
        [
            doc(1, "2023-04-28", "Apr 28 2023 Special Council Meeting Agenda", council),
            doc(2, "2023-04-28", "Apr 28 2023 Special Council Meeting Minutes", council),
            doc(
                4,
                "2023-04-28",
                "Apr 28 2023 Special Council Meeting Minutes (Conf. order lifted)",
                council,
            ),
            doc(
                3,
                "2023-04-28",
                "Apr 28 2023 Special Council Meeting Agenda (Conf. order lifted)",
                council,
            ),
        ],
        2023,
    ) == [("2023-04-28", "Special Council Meeting", url(1), url(4))]


def test_an_agenda_filed_with_and_without_attachments_is_the_agenda():
    # Streaky Bay's 19 March 2024 meeting lost its agenda: the base class
    # dropped both copies as attachments.
    label = "Council Meetings"
    assert scrape(
        StreakyBayScraper,
        [
            doc(
                1,
                "2024-03-19",
                "Council Agenda - 19 March 2024 - With Attachments",
                label,
                filename="Council-Agenda-19-March-2024-With-Attachments-compressed-1.pdf",
            ),
            doc(
                2,
                "2024-03-19",
                "Council Agenda - 19 March 2024 - No Attachments",
                label,
                filename="Council-Agenda-19-March-2024-No-Attachments.pdf",
            ),
            doc(3, "2024-03-19", "Council Minutes - 19 March 2024", label),
        ],
        2024,
    ) == [("2024-03-19", "Council Meeting", url(2), url(3))]


def test_the_council_fails_when_its_own_listing_fails_and_its_panels_does_not():
    # The base class would return the panel's meetings alone, a quietly
    # short list.
    scraper = BarungaWestScraper()
    scraper.years_filter = [2026]
    council, panel = (scraper._page_url(u) for u in scraper.listing_urls)
    scraper.fetcher = PlaybackFetcher(
        [
            [["selenium", council], encode_failure(TimeoutError("challenge"))],
            [
                ["selenium", panel],
                as_listing_page(
                    [
                        doc(1, "2026-03-10", "CAP Agenda 10 March 2026", "CAP"),
                        doc(2, "2026-03-10", "CAP Minutes 10 March 2026", "CAP"),
                    ]
                ),
            ],
        ]
    )
    with pytest.raises(RuntimeError, match="council's own listing"):
        scraper.scraper()
