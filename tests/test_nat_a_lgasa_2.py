"""The rules `RegionalLGASAScraper` adds for the regional LGA SA councils.

The cassettes replay each council end to end, but a re-record accepts any
change in which paper becomes the agenda, and they are recorded unfiltered,
so they never show what a one-year production run requests. These pin both,
each with a case taken from a real collection, through the real councils'
`scraper()` and their own listing URLs.
"""

import pytest

from aus_council_scrapers.scrapers.sa.berri_barmera import BerriBarmeraScraper
from aus_council_scrapers.scrapers.sa.clare_gilbert_valleys import (
    ClareGilbertValleysScraper,
)
from aus_council_scrapers.scrapers.sa.grant import GrantSAScraper
from aus_council_scrapers.scrapers.sa.loxton_waikerie import LoxtonWaikerieScraper
from aus_council_scrapers.scrapers.sa.naracoorte_lucindale import (
    NaracoorteLucindaleScraper,
)
from aus_council_scrapers.scrapers.sa.renmark_paringa import RenmarkParingaScraper
from tests.test_lgasa import _ListingSite, as_listing_page, doc, url


def scrape(scraper_class, documents, year):
    """Run a council over one listing page holding `documents`; any further
    listing it reads is empty. Returns the meetings and the URLs requested."""
    scraper = scraper_class()
    scraper.years_filter = [year]
    listings = scraper_class.listing_urls + tuple(
        listing for listing, _ in scraper_class.historic_listings
    )
    pages = {scraper._page_url(listing): as_listing_page([]) for listing in listings}
    pages[scraper._page_url(listings[0])] = as_listing_page(documents)
    site = _ListingSite(pages)
    scraper.fetcher = site
    meetings = [
        (r.date, r.name, r.agenda_url, r.minutes_url) for r in scraper.scraper()
    ]
    return meetings, site.requested


def test_a_title_date_near_the_filed_one_decides_the_meeting_date():
    # Naracoorte Lucindale filed both papers of its 22 March 2022 meeting
    # under the 17th, a Thursday; the council meets on Tuesdays. A title
    # naming another *year* is a typo in the title, not a misfiling: its
    # 25 February 2025 agenda is titled "2024.02.25".
    committee = "Council Meetings"
    meetings, _ = scrape(
        NaracoorteLucindaleScraper,
        [
            doc(
                1121627,
                "2022-03-17",
                "2022-03-22 Council Agenda & Attachments",
                committee,
            ),
            doc(1124694, "2022-03-17", "2022-03-22 Council Minutes", committee),
        ],
        2022,
    )
    assert meetings == [("2022-03-22", "Council Meeting", url(1121627), url(1124694))]

    meetings, _ = scrape(
        NaracoorteLucindaleScraper,
        [
            doc(
                1762000,
                "2025-02-25",
                "2024.02.25 Council Agenda & Attachments",
                committee,
            ),
            doc(1765000, "2025-02-25", "2025.02.25 Council Minutes", committee),
        ],
        2025,
    )
    assert meetings == [("2025-02-25", "Council Meeting", url(1762000), url(1765000))]


def test_two_sittings_told_apart_only_by_their_minutes_keep_their_own_papers():
    # Berri Barmera, 26 April 2022: the special budget meeting's agenda does
    # not say "agenda", so only the minutes show there were two meetings.
    committee = "Full Council - Agenda and Minutes"
    meetings, _ = scrape(
        BerriBarmeraScraper,
        [
            doc(
                1138175,
                "2022-04-26",
                "2022 Ordinary Council Meeting Agenda 26 April",
                committee,
            ),
            doc(
                1138554,
                "2022-04-26",
                "2022 Special Meeting of Council - Third Budget 26 April 2022",
                committee,
            ),
            doc(
                1141244,
                "2022-04-26",
                "2022 Special Meeting of Council Minutes 26 April",
                committee,
            ),
            doc(
                1141246,
                "2022-04-26",
                "2022 Ordinary Meeting of Council Minutes 26 April",
                committee,
            ),
        ],
        2022,
    )
    assert sorted(meetings) == [
        ("2022-04-26", "Council Meeting", url(1138175), url(1141246)),
        ("2022-04-26", "Special Council Meeting", url(1138554), url(1141244)),
    ]


def test_minutes_that_omit_the_kind_of_sitting_do_not_become_a_meeting():
    # Grant held one special meeting on 24 June 2026, and filed its minutes
    # twice: "Special Meeting Minutes" and plain "Minutes".
    committee = "Ordinary Council Meetings"
    meetings, _ = scrape(
        GrantSAScraper,
        [
            doc(
                2004001, "2026-06-24", "24 June 2026 Special Meeting Agenda", committee
            ),
            doc(
                2005083, "2026-06-24", "24 June 2026 Special Meeting Minutes", committee
            ),
            doc(2026291, "2026-06-24", "24 June 2026 Minutes", committee),
        ],
        2026,
    )
    assert meetings == [
        ("2026-06-24", "Special Council Meeting", url(2004001), url(2005083))
    ]


def test_two_special_meetings_with_one_title_are_paired_by_start_time():
    # Grant, 27 January 2022: both agendas are titled alike and only their
    # file names give the start time; the minutes say "First"/"Second".
    # Checked against the PDFs: 1095601 is the 5.30 pm agenda, 1099058 the
    # 5.30 pm minutes.
    committee = "Ordinary Council Meetings"
    meetings, _ = scrape(
        GrantSAScraper,
        [
            doc(
                1095597,
                "2022-01-27",
                "27 January 2022 Special Meeting Agenda",
                committee,
                "Special-Council-Agenda-27-January-2022-6.30-for-website.pdf",
            ),
            doc(
                1095601,
                "2022-01-27",
                "27 January 2022 Special Meeting Agenda",
                committee,
                "Agenda-Special-Meeting-27-January-5.30PM-Web.pdf",
            ),
            doc(
                1099058,
                "2022-01-27",
                "27 January 2022 Minutes (First Meeting)",
                committee,
            ),
            doc(
                1099152,
                "2022-01-27",
                "27 January 2022 Minutes (Second Meeting)",
                committee,
            ),
        ],
        2022,
    )
    assert sorted(meetings) == [
        ("2022-01-27", "Special Council Meeting", url(1095597), url(1099152)),
        ("2022-01-27", "Special Council Meeting", url(1095601), url(1099058)),
    ]


def test_informal_gatherings_filed_as_council_papers_are_not_meetings():
    # Renmark Paringa, 8 September 2026: a briefing session on the evening of
    # a special meeting, and one on 11 August on its own, both under the
    # council's label and titled "Agenda - ...".
    committee = "Council (General Council)"
    meetings, _ = scrape(
        RenmarkParingaScraper,
        [
            doc(
                2039905,
                "2026-09-08",
                "Agenda - Special Council Meeting - 8 September 2026",
                committee,
            ),
            doc(
                2039668,
                "2026-09-08",
                "Agenda - Briefing Session of Council - 8 September 2026",
                committee,
            ),
            doc(
                2044987,
                "2026-09-08",
                "Minutes - Special Council Meeting - 8 September 2026",
                committee,
            ),
            doc(
                2026973,
                "2026-08-11",
                "Agenda - Briefing Session of Council - 11 August 2026",
                committee,
            ),
        ],
        2026,
    )
    assert meetings == [
        ("2026-09-08", "Special Council Meeting", url(2039905), url(2044987))
    ]


def test_a_stopped_listing_is_read_only_by_a_run_wanting_its_years():
    # Grant's Council Assessment Panel listing ends in 2022. Production asks
    # for the current year, and must not pay a page and a 20 s crawl delay
    # for it every night.
    cap = GrantSAScraper()._page_url("https://www.slcc.sa.gov.au/council/meetings/cap")

    _, requested = scrape(GrantSAScraper, [], 2026)
    assert cap not in requested
    assert len(requested) == len(GrantSAScraper.listing_urls)

    _, requested = scrape(GrantSAScraper, [], 2022)
    assert cap in requested


def test_a_file_name_agreeing_with_the_filed_date_outvotes_the_title():
    # Clare and Gilbert Valleys filed its Reconciliation Advisory Group
    # agenda under 30 November 2021 and titled it "20 November 2021", a
    # Saturday. The PDF and the file name say Tuesday the 30th.
    meetings, _ = scrape(
        ClareGilbertValleysScraper,
        [
            doc(
                1069338,
                "2021-11-30",
                "20 November 2021 Reconciliation Advisory Group Agenda",
                "Reconciliation Advisory Group",
                "Reconciliation-Advisory-Group-meeting-30-November-21.pdf",
            )
        ],
        2021,
    )
    assert meetings == [
        ("2021-11-30", "Reconciliation Advisory Group", url(1069338), None)
    ]


def test_papers_whose_file_names_agree_on_a_date_are_one_meeting_on_it():
    # Naracoorte Lucindale's Audit Committee met on 16 February 2021. Both
    # papers are titled with the 12th, the day the notice went out, and the
    # minutes are filed under it; both file names and both PDFs say the 16th.
    meetings, _ = scrape(
        NaracoorteLucindaleScraper,
        [
            doc(
                845894,
                "2021-02-12",
                "Audit Committee Minutes 12 February 2021",
                "Audit",
                "06-Audit-Committee-Minutes-16-February-2021.pdf",
            ),
            doc(
                841011,
                "2021-02-16",
                "Audit Committee Agenda & Attachments 12 February 2021",
                "Audit",
                "06-Audit-Committee-Agenda-and-Attachments-16-February-2021.pdf",
            ),
        ],
        2021,
    )
    assert meetings == [("2021-02-16", "Audit Committee", url(841011), url(845894))]


def test_a_paper_of_another_year_is_dropped_unless_it_is_a_year_typo():
    # Renmark Paringa filed its 28 May 2019 agenda under 28 May 2020, where
    # it stood alone as a meeting that never happened.
    committee = "Council (General Council)"
    meetings, _ = scrape(
        RenmarkParingaScraper,
        [
            doc(
                775783,
                "2020-05-28",
                "Agenda - Ordinary Council Meeting - 28 May 2019",
                committee,
                "OCM-Agenda-28-May-19-public-copy.pdf",
            )
        ],
        2020,
    )
    assert meetings == []

    # Loxton Waikerie's minutes of 21 January 2021 are titled and named
    # "21 January 2020" (the PDF says 2021), beside that meeting's agenda.
    committee = "Agendas & Minutes"
    meetings, _ = scrape(
        LoxtonWaikerieScraper,
        [
            doc(
                828923,
                "2021-01-21",
                "Special Council Meeting Agenda - 21 January 2021",
                committee,
                "Special-Council-Meeting-Agenda-21-January-2021.pdf",
            ),
            doc(
                830087,
                "2021-01-21",
                "Special Council Meeting Minutes - 21 January 2020",
                committee,
                "Special-Council-Meeting-Minutes-21-January-2020.pdf",
            ),
        ],
        2021,
    )
    assert meetings == [
        ("2021-01-21", "Special Council Meeting", url(828923), url(830087))
    ]


def test_minutes_adjourned_to_another_day_go_to_that_sitting():
    # Clare and Gilbert Valleys adjourned its 20 May 2026 meeting to the
    # 25th; the adjourned sitting's minutes are filed under the 20th.
    committee = "Ordinary & Special Council Meetings"
    meetings, _ = scrape(
        ClareGilbertValleysScraper,
        [
            doc(
                1985537,
                "2026-05-20",
                "20 May 2026 Ordinary Council Meeting Agenda",
                committee,
            ),
            doc(
                1989926,
                "2026-05-20",
                "20 May 2026 Ordinary Council Meeting Minutes",
                committee,
            ),
            doc(
                1991403,
                "2026-05-20",
                "20 May 2026 Ordinary Council Meeting Minutes - Adjourned to "
                "25 May 2026",
                committee,
            ),
            doc(
                1988313,
                "2026-05-25",
                "25 May 2026 Adjourned Ordinary Council Meeting Notice",
                committee,
                "1.-20-May-2026-Notice-of-Adjourned-Meeting.pdf",
            ),
        ],
        2026,
    )
    assert meetings == [
        ("2026-05-25", "Council Meeting", url(1988313), url(1991403)),
        ("2026-05-20", "Council Meeting", url(1985537), url(1989926)),
    ]


def test_one_body_filed_under_two_labels_is_one_meeting():
    # Clare and Gilbert Valleys, 20 July 2022: the CEO panel's agenda under
    # "CEO Performance Management Panel", its minutes under "Chief Executive
    # Officer Panel".
    meetings, _ = scrape(
        ClareGilbertValleysScraper,
        [
            doc(
                1178715,
                "2022-07-20",
                "20 July 2022 CEO Panel Meeting Agenda",
                "CEO Performance Management Panel",
            ),
            doc(
                1194942,
                "2022-07-20",
                "20 July CEO Panel Meeting Minutes",
                "Chief Executive Officer Panel",
            ),
        ],
        2022,
    )
    assert meetings == [
        ("2022-07-20", "Chief Executive Officer Panel", url(1178715), url(1194942))
    ]

    # Naracoorte Lucindale, 13 April 2023: the Audit & Risk Committee's
    # agenda left under the old label "Audit".
    meetings, _ = scrape(
        NaracoorteLucindaleScraper,
        [
            doc(
                1319722,
                "2023-04-13",
                "2023.04.13 Audit & Risk Committee Agenda & Attachments",
                "Audit",
            ),
            doc(
                1324062,
                "2023-04-13",
                "2023.04.13 Audit & Risk Committee Minutes",
                "Audit & Risk",
            ),
        ],
        2023,
    )
    assert meetings == [
        ("2023-04-13", "Audit & Risk Committee", url(1319722), url(1324062))
    ]


def test_two_special_meetings_with_numbered_minutes_keep_their_own_papers():
    # Berri Barmera, 1 June 2021, at 5.30 pm and 7 pm. Only the second
    # agenda gives its time, and the second minutes do not say "minutes".
    # Checked against the four PDFs.
    committee = "Full Council - Agenda and Minutes"
    meetings, _ = scrape(
        BerriBarmeraScraper,
        [
            doc(
                906563,
                "2021-06-01",
                "2021 Special Meeting of Council Agenda 1 June 2021 (7:00pm)",
                committee,
                "Public-Special-Council-Meeting-Agenda-1-June-2021.pdf",
            ),
            doc(
                905045,
                "2021-06-01",
                "2021 Special Meeting of Council Agenda 1 June 2021",
                committee,
                "Special-Council-Meeting-1-June-2021.pdf",
            ),
            doc(
                909360,
                "2021-06-01",
                "2021 Special Meeting of Council 1 June (2)",
                committee,
                "Special-Council-Meeting-Minutes-2-1-June-2021.pdf",
            ),
            doc(
                909325,
                "2021-06-01",
                "2021 Special Meeting of Council Minutes 1 June (1)",
                committee,
                "Special-Council-Meeting-Minutes-1-1-June-2021.pdf",
            ),
        ],
        2021,
    )
    assert sorted(meetings) == [
        ("2021-06-01", "Special Council Meeting", url(905045), url(909325)),
        ("2021-06-01", "Special Council Meeting", url(906563), url(909360)),
    ]


def test_a_revised_paper_beats_the_original():
    # Loxton Waikerie, 19 November 2025: "V2" of the agenda, uploaded later.
    committee = "Agendas & Minutes"
    meetings, _ = scrape(
        LoxtonWaikerieScraper,
        [
            doc(
                1897487,
                "2025-11-19",
                "Council Meeting Agenda - 19 November 2025",
                committee,
            ),
            doc(
                1900627,
                "2025-11-19",
                "V2 Council Meeting Agenda - 19 November 2025",
                committee,
            ),
        ],
        2025,
    )
    assert meetings == [("2025-11-19", "Council Meeting", url(1900627), None)]


def test_a_lost_council_listing_fails_the_council():
    # Loxton Waikerie reads its council page and the Riverland panel's. With
    # the council page lost, a run must fail rather than report the panel's
    # meetings alone, and not spend a page and a crawl delay on the panel.
    scraper = LoxtonWaikerieScraper()
    scraper.years_filter = [2026]
    council, panel = LoxtonWaikerieScraper.listing_urls
    site = _ListingSite({scraper._page_url(panel): as_listing_page([])})
    site.restart_driver = lambda: None
    scraper.fetcher = site
    with pytest.raises(RuntimeError, match="council's own listing"):
        scraper.scraper()
    assert site.requested == [scraper._page_url(council)] * 2

    # A lost panel listing is a warning, as in the base class.
    scraper = LoxtonWaikerieScraper()
    scraper.years_filter = [2026]
    site = _ListingSite(
        {
            scraper._page_url(council): as_listing_page(
                [
                    doc(
                        2000001,
                        "2026-05-20",
                        "Council Meeting Agenda - 20 May 2026",
                        "Agendas & Minutes",
                    )
                ]
            )
        }
    )
    site.restart_driver = lambda: None
    scraper.fetcher = site
    assert [r.date for r in scraper.scraper()] == ["2026-05-20"]
