"""Rules `LGASAFunnelbackScraper` gained for Franklin Harbour, Kangaroo
Island, Peterborough and Ceduna.

Like `test_lgasa.py`, these pin rules a re-record would silently accept
losing. Every case is a real document from those collections, driven through
`scraper()` with the helpers there.
"""

from tests.test_lgasa import _Scraper, doc, scrape, url


def test_minutes_published_with_their_attachments_are_the_minutes():
    # Franklin Harbour publishes every council meeting's minutes this way;
    # an attachment filed on its own is still never either paper.
    results = [
        doc(1, "2026-07-08", "July 2026 Notice of Meeting & Agenda"),
        doc(2, "2026-07-08", "July 2026 Minutes & Attachments"),
        doc(3, "2022-01-19", "January 2022 Notice of Meeting & Agenda"),
        doc(4, "2022-01-19", "2022 January Minutes, Reports & Attachments"),
        doc(5, "2020-08-12", "2020 August Attachment Part 1"),
    ]
    assert scrape(results, year=2026) == [
        ("2026-07-08", "Council Meeting", url(1), url(2)),
    ]
    assert scrape(results, year=2022) == [
        ("2022-01-19", "Council Meeting", url(3), url(4)),
    ]
    assert scrape(results, year=2020) == []


def test_month_titled_papers_filed_apart_are_one_meeting_on_the_day_their_files_name():
    # Franklin Harbour: August 2026's agenda filed under the 7th, the minutes
    # under the 14th; the agenda file is for the 12th. June 2020's agenda is
    # filed under the 4th, its publication day; the minutes file is for the
    # 10th. December 2023 names no day anywhere, so the agenda's date stands.
    results = [
        doc(
            1,
            "2026-08-07",
            "August 2026 Notice of Meeting & Agenda",
            filename="120826-Notice-of-Meeting-and-Agenda.pdf",
        ),
        doc(
            2,
            "2026-08-14",
            "August 2026 Minutes & Attachments",
            filename="August-2026-Minutes-and-Attachments.pdf",
        ),
        doc(
            3,
            "2020-06-04",
            "2020 June Agenda and Notice of Meeting",
            filename="june-2020-agenda-and-notice-of-meeting.pdf",
        ),
        doc(
            4,
            "2020-06-10",
            "2020 June Minutes, Reports and Attachments",
            filename="100620.Minutes.Reports-and-Attachments.pdf",
        ),
        doc(5, "2023-12-13", "December 2023 Notice of Meeting & Agenda"),
        doc(6, "2023-12-01", "December 2023 Minutes & Attachments"),
    ]
    assert scrape(results, year=2026) == [
        ("2026-08-12", "Council Meeting", url(1), url(2)),
    ]
    assert scrape(results, year=2020) == [
        ("2020-06-10", "Council Meeting", url(3), url(4)),
    ]
    assert scrape(results, year=2023) == [
        ("2023-12-13", "Council Meeting", url(5), url(6)),
    ]


def test_a_notice_of_meeting_adjournment_is_not_an_agenda():
    # Franklin Harbour adjourned its 14 September 2022 meeting to the 19th.
    results = [
        doc(1, "2022-09-14", "September 2022 Notice of Meeting Adjournment"),
        doc(2, "2022-09-19", "September 2022 Notice of Meeting & Agenda"),
        doc(3, "2022-09-19", "September 2022 Minutes & Attachments"),
    ]
    assert scrape(results, year=2022) == [
        ("2022-09-19", "Council Meeting", url(2), url(3)),
    ]


class _KangarooIsland(_Scraper):
    body_from_title = (
        (r"\baudit\b", "Audit and Risk Committee"),
        (r"\binformation\W*br(?:ie|ei)fing\b", "Information Briefing Session"),
    )
    notice_committees = frozenset({"Information Briefing Session"})


def test_bodies_named_in_titles_are_their_own_meetings():
    # Kangaroo Island files everything under "Council Meetings". A briefing
    # session on the night of a council meeting must not lend it an agenda,
    # and a lone notice is the session's agenda.
    results = [
        doc(1, "2025-08-12", "Council Agenda 2025-08-12"),
        doc(2, "2025-08-12", "Council Minutes 2025-08-12"),
        doc(3, "2025-08-12", "2025-08-12 Information Briefing Session Agenda"),
        doc(4, "2025-09-24", "Information Briefing Notice 2025-09-24"),
        doc(5, "2025-09-29", "Special Audit and Risk Committee Agenda 2025-09-29"),
    ]
    assert scrape(results, scraper_class=_KangarooIsland) == [
        ("2025-09-29", "Special Audit and Risk Committee", url(5), None),
        ("2025-09-24", "Information Briefing Session", url(4), None),
        ("2025-08-12", "Information Briefing Session", url(3), None),
        ("2025-08-12", "Council Meeting", url(1), url(2)),
    ]


def test_a_file_name_naming_the_other_kind_overrules_the_title():
    # Kangaroo Island's "Council Agenda 2025-07-08" is the minutes file.
    results = [
        doc(
            1834544,
            "2025-07-08",
            "Council Agenda 2025-07-08",
            filename="Council-Agenda-20250708.pdf",
        ),
        doc(
            1837876,
            "2025-07-08",
            "Council Agenda 2025-07-08",
            filename="20250708-Council-Minutes.pdf",
        ),
    ]
    assert scrape(results) == [
        ("2025-07-08", "Council Meeting", url(1834544), url(1837876)),
    ]


class _Peterborough(_Scraper):
    title_kinds = (
        (r"^(?:Special |Sp )?(?:Counci?l? )?(?:Meeting )?Report\b", "agenda", -1),
    )


def test_council_rules_choose_the_business_paper_over_the_notice():
    # Peterborough before September 2025: a one-page "Council NOM" and the
    # full "Council Report". Without a rule the NOM is still the agenda, and
    # "Sp" is a special meeting.
    results = [
        doc(1777171, "2025-03-17", "Council NOM 17/03/25"),
        doc(1777381, "2025-03-17", "Council Report 17/03/25"),
        doc(1780346, "2025-03-17", "Council Meeting Minutes 17/03/25"),
        doc(10, "2025-07-25", "Sp Council Minutes 25/07/25"),
    ]
    assert scrape(results, scraper_class=_Peterborough) == [
        ("2025-07-25", "Special Council Meeting", None, url(10)),
        ("2025-03-17", "Council Meeting", url(1777381), url(1780346)),
    ]
    assert scrape(results)[1] == (
        "2025-03-17",
        "Council Meeting",
        url(1777171),
        url(1780346),
    )


def test_the_business_paper_outranks_a_short_paper_titled_agenda():
    # Peterborough until mid-2021: "Council Agenda 17/08/20" is three pages
    # (the notice and the index), uploaded before the 98-page "Council Report
    # 17/08/20 v2". Ranked level, the lower asset id chose the short one.
    results = [
        doc(730904, "2020-08-17", "Council Agenda 17/08/20"),
        doc(731731, "2020-08-17", "Council Report 17/08/20 v2"),
        doc(733195, "2020-08-17", "Council Minutes 17/08/20"),
    ]
    assert scrape(results, year=2020, scraper_class=_Peterborough) == [
        ("2020-08-17", "Council Meeting", url(731731), url(733195)),
    ]


def test_two_digit_year_titles_rejoin_a_misdated_minutes():
    # Peterborough filed the minutes of its 1 July 2025 special meeting
    # under the 7th; both titles say 01/07/25.
    results = [
        doc(1, "2025-07-01", "Special Council Meeting NOM 01/07/25"),
        doc(2, "2025-07-07", "Special Council Meeting Minutes 01/07/25"),
    ]
    assert scrape(results) == [
        ("2025-07-01", "Special Council Meeting", url(1), url(2)),
    ]


def test_confidential_minutes_filed_on_their_release_day_make_no_meeting():
    # Ceduna released its 21 August 2024 confidential minutes a year later.
    # Filed beside the meeting itself, a release is still a weaker candidate.
    results = [
        doc(1, "2025-08-21", "Released from Confidence Minutes - 21 August 2024"),
        doc(2, "2025-08-20", "Released from Confidence Minutes - 20 August 2025"),
        doc(3, "2025-08-20", "Ordinary Council Meeting Minutes - 20 August 2025"),
    ]
    assert scrape(results) == [
        ("2025-08-20", "Council Meeting", None, url(3)),
    ]


class _Restating(_Scraper):
    restate_lone_dates = True


def test_a_lone_paper_moves_to_the_date_its_title_and_file_agree_on():
    # Kangaroo Island filed its 24 May 2022 special agenda under the 20th.
    # Its "13-6-2021" informal gathering agenda is "20210713-..." and filed
    # 13 July: the title is the mistake, so it stays.
    results = [
        doc(
            1,
            "2022-05-20",
            "Special Council Meeting Agenda 2022-05-24",
            filename="20220524-Special-Council.pdf",
        ),
        doc(
            2,
            "2022-05-24",
            "Special Council Minutes 2022-05-24",
            filename="Special-Council-Minutes-2022-05-24.pdf",
        ),
        doc(
            3,
            "2021-07-13",
            "Special Informal Gathering Agenda 13-6-2021",
            filename="20210713-Special-Informal-Gathering.pdf",
        ),
    ]
    assert scrape(results, year=2022, scraper_class=_Restating) == [
        ("2022-05-24", "Special Council Meeting", url(1), url(2)),
    ]
    assert [
        d for d, _, _, _ in scrape(results, year=2021, scraper_class=_Restating)
    ] == ["2021-07-13"]


def test_a_month_titled_paper_on_the_placeholder_is_dated_by_its_minutes():
    # Franklin Harbour filed "January 2024 Notice of Meeting & Agenda" under
    # Matrix's 1 January placeholder; the minutes are filed under the 17th,
    # and the notice says Wednesday 17 January. Without a partner the paper
    # is dropped, never emitted on the 1st; without `restate_lone_dates` it
    # is dropped as before.
    agenda = doc(1528162, "2024-01-01", "January 2024 Notice of Meeting & Agenda")
    minutes = doc(1536117, "2024-01-17", "January 2024 Minutes & Attachments")
    assert scrape([agenda, minutes], year=2024, scraper_class=_Restating) == [
        ("2024-01-17", "Council Meeting", url(1528162), url(1536117)),
    ]
    assert scrape([agenda], year=2024, scraper_class=_Restating) == []
    assert scrape([agenda, minutes], year=2024) == [
        ("2024-01-17", "Council Meeting", None, url(1536117)),
    ]
