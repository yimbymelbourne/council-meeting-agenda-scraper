"""Kalgoorlie-Boulder's papers page: the cases its recorded fixture cannot show.

The fixture covers the page as it stands (every Council heading there carries
its year). These pin what happens when a heading leaves the year off, which
the page already does for a committee ("Audit, Risk and Improvement
Committee Meeting: 10 September"): the year may come from the folder the
papers are filed in, but never from a guess.
"""

from aus_council_scrapers.scrapers.wa.kalgoorlie_boulder import (
    KalgoorlieBoulderScraper,
)

_DOCS = "https://www.ckb.wa.gov.au/Profiles/ckb/Assets/ClientData/Documents/Governance"

_PAGE = f"""
<html><body><div id="r-speaker">
<div class="accordion">
<h2>Ordinary Council Meeting: 17 November&nbsp;</h2>
<p><a href="{_DOCS}/2026_Meetings/OCM/Nov26/OCM_17_Nov_-_Agenda.pdf">Agenda</a></p>
<p><a href="{_DOCS}/2026_Meetings/OCM/Nov26/OCM_17_Nov_-_Attachments.pdf">Attachments</a></p>
</div>
<div class="accordion">
<h2>Special Council Meeting: 3 November</h2>
<p><a href="{_DOCS}/Agenda/SCM_3_Nov_-_Agenda.pdf">Agenda</a></p>
</div>
<div class="accordion">
<h2>Audit, Risk and Improvement Committee: 4 November 2026</h2>
<p><a href="{_DOCS}/2026_Meetings/ARIC/ARIC_4_Nov_2026_-_Agenda.pdf">Agenda</a></p>
</div>
</div></body></html>
"""


def _scrape(page: str):
    scraper = KalgoorlieBoulderScraper()
    scraper.fetcher.fetch_with_requests = lambda url, *a, **k: page
    scraper.years_filter = [2026]
    return scraper.scraper()


def test_year_left_off_a_heading_comes_from_the_papers_folder_or_not_at_all():
    meetings = _scrape(_PAGE)

    # The Ordinary meeting's papers sit under 2026_Meetings, so its day and
    # month are the heading's and its year the folder's. The Special
    # meeting's papers name no year anywhere: it is left out, not dated.
    # The committee is not a Council meeting.
    assert [(m.name, m.date, m.agenda_url) for m in meetings] == [
        (
            "Ordinary Council Meeting",
            "2026-11-17",
            f"{_DOCS}/2026_Meetings/OCM/Nov26/OCM_17_Nov_-_Agenda.pdf",
        )
    ]


# The tidy layer's bundled-tail rule (see councilconnect_tidy's module doc).
# The fixtures hold the two cases that motivated it, Geraldton's 24 March 2020
# agenda and Katherine's 27 May 2025 minutes; these pin the guard the
# fixtures cannot show: a late item stays a late item when it too says what
# it bundles.
_MEETING = "https://www.example.wa.gov.au/council-meetings/ordinary-council-meeting/x/1/documents"


def test_a_filename_saying_what_it_includes_keeps_the_agenda_but_not_a_late_item():
    from aus_council_scrapers.scrapers.nt.katherine import KatherineScraper

    pick = KatherineScraper()._pick_documents

    whole = (
        f"{_MEETING}/agenda-ordinary-meeting-24-march-2020-website-incl-late-item.pdf"
    )
    minutes = (
        f"{_MEETING}/minutes-confirmed-including-207-report-and-notice-of-motion.pdf"
    )
    assert pick(
        [
            ("Agenda", "Agenda - Ordinary Meeting", whole),
            ("Minutes", "Minutes", minutes),
        ]
    ) == (whole, minutes)

    late = f"{_MEETING}/late-item-agenda-incl-attachments.pdf"
    assert pick([("Agenda", "Late Item Agenda", late)]) == (None, None)
    assert pick([("Agenda", "Agenda", late)]) == (None, None)
