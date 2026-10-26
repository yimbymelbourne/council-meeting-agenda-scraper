"""Date and pairing rules for councils whose labels cannot be trusted.

Coonamble labels give only the month, so the day comes from file names, and
only some file names are honest about it. Cobar links some documents from
the wrong row, and so does Irwin, whose wrong agenda would also change the
meeting's type. The recorded fixtures exercise both, but a re-record after a
site change would accept a regression silently, and a wrong meeting date is
the defect these rules exist to prevent, so they are pinned here through
`scraper()`.
"""

from aus_council_scrapers.base import Fetcher
from aus_council_scrapers.scrapers.nsw.cobar import CobarScraper
from aus_council_scrapers.scrapers.nsw.coonamble import CoonambleScraper
from aus_council_scrapers.scrapers.wa.irwin import IrwinScraper


class _Pages(Fetcher):
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def fetch_with_requests(self, url, method="GET", **kwargs) -> str:
        return self.pages[url]

    def get_selenium_driver(self):
        raise AssertionError("plain HTML")

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise AssertionError("plain HTML")


def _coonamble_paper(label: str, href: str) -> str:
    return f'<table><tr><td><a href="{href}">{label}</a></td></tr></table>'


def test_coonamble_dates_from_business_papers_never_from_minutes_upload_prefixes():
    media = "/__media_downloads/business-papers-minutes/2025"
    page = "".join(
        [
            # The business paper's "yymmdd_" prefix is the meeting date; the
            # minutes' prefix is an upload date a week earlier (as June 2025
            # really is), and must not split or move the meeting.
            _coonamble_paper(
                "1. Business Paper - Ordinary Meeting June 2025",
                f"{media}/250618_1._Business_Paper_-_Ordinary_Meeting_June_2025.PDF",
            ),
            _coonamble_paper(
                "2. Minutes - Ordinary Meeting June 2025",
                f"{media}/250611_2._Minutes_-_Ordinary_Meeting_June_2025.pdf",
            ),
            # No paper names a day, and the minutes' prefix is not evidence:
            # the meeting is left out rather than given an invented day.
            _coonamble_paper(
                "1. Business Paper - Ordinary Meeting May 2025",
                "/ORDINARY%20BUSINESS%20PAPER%20MAY%202025%20REVISED.pdf",
            ),
            _coonamble_paper(
                "2. Minutes - Ordinary Meeting May 2025",
                f"{media}/250515_2._Minutes_-_Ordinary_Meeting_May_2025.pdf",
            ),
        ]
    )
    scraper = CoonambleScraper()
    scraper.years_filter = [2025]
    scraper.fetcher = _Pages(
        {
            "https://www.coonambleshire.nsw.gov.au/council/council-meetings": page,
            "https://www.coonambleshire.nsw.gov.au/council/previous-years": page,
        }
    )

    results = scraper.scraper()

    assert [
        (r.date, r.agenda_url.rsplit("/", 1)[-1], r.minutes_url.rsplit("/", 1)[-1])
        for r in results
    ] == [
        (
            "2025-06-18",
            "250618_1._Business_Paper_-_Ordinary_Meeting_June_2025.PDF",
            "250611_2._Minutes_-_Ordinary_Meeting_June_2025.pdf",
        )
    ]


def test_cobar_drops_documents_filed_against_another_meeting():
    uploads = "https://www.cobar.nsw.gov.au/wp-content/uploads"

    def row(month, day, agenda, minutes):
        return (
            f"<tr><td>{month}</td><td>{day}</td>"
            f'<td><a href="{uploads}/{agenda}">Ordinary Agenda</a></td><td></td><td></td>'
            f'<td><a href="{uploads}/{minutes}">Minutes</a></td></tr>'
        )

    table = "".join(
        [
            "<tr><td>Month</td><td>Date</td><td>Business Papers</td><td>Attachments</td>"
            "<td>Supplementary Reports</td><td>Minutes</td></tr>",
            # The February 2021 row links December 2020's minutes.
            row(
                "February",
                "25",
                "25.02.2021_-_Ordinary_Meeting_Agenda.pdf",
                "10.12.2020_-_Council_Meeting_Minutes.pdf",
            ),
            # The March row's "Minutes" link is the agenda again.
            row(
                "March",
                "25",
                "25.03.2021_-_Ordinary_Agenda.pdf",
                "March-Ordinary-Council-Meeting-Agenda.pdf",
            ),
        ]
    )
    page = (
        '<div class="elementor-accordion-item"><div class="elementor-tab-title">2021</div>'
        f'<div class="elementor-tab-content"><table>{table}</table></div></div>'
    )
    scraper = CobarScraper()
    scraper.years_filter = [2021]
    scraper.fetcher = _Pages(
        {"https://www.cobar.nsw.gov.au/council/about-council/council-meetings/": page}
    )

    results = scraper.scraper()

    assert [
        (r.date, r.agenda_url.rsplit("/", 1)[-1], r.minutes_url) for r in results
    ] == [
        ("2021-02-25", "25.02.2021_-_Ordinary_Meeting_Agenda.pdf", None),
        ("2021-03-25", "25.03.2021_-_Ordinary_Agenda.pdf", None),
    ]


def test_irwin_drops_another_meetings_special_agenda_and_reads_scanned_minutes():
    site = "https://irwin.wa.gov.au"
    year_2023 = f"{site}/council-meetings-2/2023-council-meetings/"
    uploads = f"{site}/wp-content/uploads"

    def row(date, time, meeting, links):
        cells = "".join(f'<a href="{href}">{label}</a>' for label, href in links)
        return (
            f"<tr><td>{date}</td><td>{time}</td><td>{meeting}</td>"
            f"<td>{cells}</td></tr>"
        )

    start = (
        f'<a href="{site}/council-meetings-2025/">2026</a>'
        f'<a href="{year_2023}">2023</a>'
        "<table>"
        # From 2025 the minutes may be scanner output whose name says
        # nothing; the "Confirmed Minutes" label is what types it.
        + row(
            "24 February 2026",
            "17:00",
            "Ordinary Council Meeting",
            [("Click Here", f"{site}/24-february-2026-ordinary-council-meeting")],
        )
        + "</table>"
    )
    post = (
        f'<a href="{uploads}/2026/02/AGENDA-Ordinary-Council-Meeting-24-February-2026.pdf">'
        "Ordinary Council Meeting Agenda</a>"
        f'<a href="{uploads}/2026/03/SKM_C55826031109240.pdf">Confirmed Minutes</a>'
    )
    # The 28 November 2023 row links the 6 November special meeting's agenda
    # beside its own ordinary minutes. The agenda goes, and with it the
    # "SCM" that would have named the row a special meeting.
    page_2023 = (
        "<table>"
        + row(
            "28 November 2023",
            "06:00",
            "Council Meeting",
            [
                ("Agenda", f"{uploads}/2023/12/1-Agenda-SCM-Nov-2023-Copy.pdf"),
                (
                    "Minutes",
                    f"{uploads}/2025/01/Council-Meeting-UNCONFIRMED-Minutes-28-November-2023.pdf",
                ),
            ],
        )
        + "</table>"
    )
    scraper = IrwinScraper()
    scraper.years_filter = [2023, 2026]
    scraper.fetcher = _Pages(
        {
            f"{site}/council-meetings-2025/": start,
            f"{site}/24-february-2026-ordinary-council-meeting": post,
            year_2023: page_2023,
        }
    )

    results = scraper.scraper()

    assert [
        (
            r.date,
            r.time,
            r.name,
            r.agenda_url and r.agenda_url.rsplit("/", 1)[-1],
            r.minutes_url.rsplit("/", 1)[-1],
        )
        for r in results
    ] == [
        (
            "2026-02-24",
            "17:00",
            "Ordinary Council Meeting",
            "AGENDA-Ordinary-Council-Meeting-24-February-2026.pdf",
            "SKM_C55826031109240.pdf",
        ),
        (
            "2023-11-28",
            None,
            "Ordinary Council Meeting",
            None,
            "Council-Meeting-UNCONFIRMED-Minutes-28-November-2023.pdf",
        ),
    ]
