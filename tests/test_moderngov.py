"""Which link on a Modern.Gov meeting page is the agenda, and which the minutes.

The cassettes prove the scrapers end to end, but a fixture diff cannot say
why a link was or was not chosen, and several of the cases below are not in
any recorded year: Sydney's pre-2020 legacy pages, a meeting with a reports
pack but no frontsheet. Each case is a mistake that would put the wrong
document in `agenda_url` or `minutes_url` while still looking like a
complete record.
"""

import pytest

from aus_council_scrapers.moderngov import ModernGovScraper

BASE = "https://meetings.example.gov.au"


class _Scraper(ModernGovScraper):
    committees = {1: "Council"}

    def __init__(self):
        super().__init__("test_council", "NSW", BASE)

    def scraper(self):
        return []


def current_page(*links, venue="Council Chamber"):
    """A current-generation meeting page: meeting-level links in div.mgLinks,
    agenda items (which also link PDFs) in the item table below."""
    items = "".join(
        f'<li><a href="{href}"{f" title={title!r}" if title else ""}>{text}</a></li>'
        for text, title, href in links
    )
    return (
        '<div id="modgov"><div class="mgLinks"><ul class="mgActionList">'
        f"{items}</ul></div>"
        '<div class="mgContent">'
        f'<p><span class="mgLabel">Venue:</span> {venue}</p>'
        '<table class="mgItemTable"><tr><td><a href="documents/s1/Confirmation'
        ' of Minutes.pdf">Confirmation of Minutes</a></td></tr></table>'
        "</div></div>"
    )


def legacy_page(*labels):
    """A legacy page. A label is the link text, or (text, filename) when the
    council's file is named differently from its label."""
    labels = [label if isinstance(label, tuple) else (label, label) for label in labels]
    rows = "".join(
        f'<tr><td><a href="Data/Council/202201171800/Agenda/{filename}.pdf">'
        f"{text}</a></td></tr>"
        for text, filename in labels
    )
    return (
        f'<div id="modgov"><div id="mgLegacyDocList"><table>{rows}</table></div></div>'
    )


FRONTSHEET = (
    "Agenda frontsheet",
    "Link to agenda frontsheet pdf file",
    "documents/g10/Agenda frontsheet 11th-Aug-2026 18.00 Council.pdf?T=0",
)
PACK = (
    "Agenda reports pack",
    "Link to agenda reports  document pack pdf file",
    "documents/g10/Public reports pack 11th-Aug-2026 18.00 Council.pdf?T=10",
)
PRINTED_MINUTES = (
    "Printed draft minutes",
    "Link to printed draft minutes pdf file",
    "documents/g10/Printed minutes 11th-Aug-2026 18.00 Council.pdf?T=1",
)


@pytest.mark.parametrize(
    "html, agenda, minutes",
    [
        pytest.param(
            current_page(FRONTSHEET, PACK, PRINTED_MINUTES),
            "/documents/g10/Agenda%20frontsheet%2011th-Aug-2026%2018.00%20Council.pdf?T=0",
            "/documents/g10/Printed%20minutes%2011th-Aug-2026%2018.00%20Council.pdf?T=1",
            # The pack is the agenda with every report bound in: 307 MB for
            # one Sydney planning meeting. The frontsheet is the agenda.
            id="frontsheet-wins-over-reports-pack",
        ),
        pytest.param(
            current_page(PACK),
            "/documents/g10/Public%20reports%20pack%2011th-Aug-2026%2018.00%20Council.pdf?T=10",
            None,
            id="reports-pack-when-there-is-no-frontsheet",
        ),
        pytest.param(
            current_page(
                FRONTSHEET,
                (
                    "Public Council Minutes - 12 July 2022",
                    None,
                    "mgChooseMDocPack.aspx?ID=490&SID=2034",
                ),
            ),
            "/documents/g10/Agenda%20frontsheet%2011th-Aug-2026%2018.00%20Council.pdf?T=0",
            "/mgChooseMDocPack.aspx?ID=490&SID=2034",
            # Adelaide, July 2022: minutes uploaded as a supporting document
            # rather than through the minutes workflow. The item table's
            # "Confirmation of Minutes" must not be taken instead.
            id="minutes-uploaded-as-a-supporting-document",
        ),
        pytest.param(
            current_page(
                FRONTSHEET,
                (
                    "Information Relevant To Item 4 - Minutes of the Audit Committee",
                    None,
                    "documents/s5/Info item 4.pdf",
                ),
                (
                    "Item 3 - Minutes of the Local Planning Panel",
                    None,
                    "documents/s6/Item 3.pdf",
                ),
            ),
            "/documents/g10/Agenda%20frontsheet%2011th-Aug-2026%2018.00%20Council.pdf?T=0",
            None,
            # Sydney puts per-item documents in div.mgLinks too. One that
            # mentions another body's minutes is an agenda item, and a
            # meeting not yet minuted must keep minutes_url empty.
            id="item-documents-mentioning-minutes-are-not-the-minutes",
        ),
        pytest.param(
            legacy_page(
                "Council Special Meeting - Agenda",
                "Council Special Meeting - Agenda - Item 4.1 - Distributed Separately",
                "Council Special Meeting - Minutes",
            ),
            "/Data/Council/202201171800/Agenda/Council%20Special%20Meeting%20-%20Agenda.pdf",
            "/Data/Council/202201171800/Agenda/Council%20Special%20Meeting%20-%20Minutes.pdf",
            id="legacy-item-distributed-separately-is-not-the-agenda",
        ),
        pytest.param(
            legacy_page(
                "Council Meeting - Agenda without conf",
                "Council Meeting - Minutes without conf",
            ),
            "/Data/Council/202201171800/Agenda/Council%20Meeting%20-%20Agenda%20without%20conf.pdf",
            "/Data/Council/202201171800/Agenda/Council%20Meeting%20-%20Minutes%20without%20conf.pdf",
            id="legacy-without-confidential-items",
        ),
        pytest.param(
            legacy_page(
                "Confirmation of Minutes",
                "Minutes by the Lord Mayor",
                "Minutes - 19 March 2018",
            ),
            None,
            "/Data/Council/202201171800/Agenda/Minutes%20-%2019%20March%202018.pdf",
            # Sydney before April 2018: one PDF per agenda item and no
            # agenda document at all. Two of those items mention minutes.
            id="legacy-per-item-pages-have-no-agenda",
        ),
        pytest.param(
            legacy_page(
                (
                    "Council - Agenda",
                    "Council Special Meeting - Minutes - 16 November 2021",
                ),
                (
                    "Council - Minutes",
                    "Council Special Meeting - Agenda - 16 November 2021",
                ),
            ),
            "/Data/Council/202201171800/Agenda/Council%20Special%20Meeting%20-%20Agenda%20-%2016%20November%202021.pdf",
            "/Data/Council/202201171800/Agenda/Council%20Special%20Meeting%20-%20Minutes%20-%2016%20November%202021.pdf",
            # Adelaide, 16 November 2021: the labels are swapped. The PDFs
            # say the filenames are right.
            id="legacy-swapped-labels-follow-the-filename",
        ),
    ],
)
def test_picks_the_meetings_own_agenda_and_minutes(html, agenda, minutes):
    found = _Scraper()._documents(html)
    assert found["agenda"] == (BASE + agenda if agenda else None)
    assert found["minutes"] == (BASE + minutes if minutes else None)


def listing(*rows):
    """A committee listing for 2025: (link text, suffix) per meeting."""
    items = "".join(
        f'<li><a class="mgMeetingTableLnk" href="ieListDocuments.aspx?CId=1&amp;MId={i}">'
        f"{text}</a> - {suffix}</li>"
        for i, (text, suffix) in enumerate(rows)
    )
    return f'<select id="YearSelect"><option value="2025">2025</option></select><ul>{items}</ul>'


def test_postponed_or_cancelled_meetings_are_skipped_unless_minuted():
    html = listing(
        # Adelaide, April 2025: an agenda went up, then the meeting was
        # postponed and never sat. Its agenda was reused at a later meeting.
        (
            "11 Apr 2025 7.30 pm",
            "Agenda, POSTPONED; Special (adjourned to 14 April 2025)",
        ),
        ("26 Apr 2025 5.30 pm", "Agenda, CANCELLED; Special"),
        # Adelaide, 25 March 2025: also marked POSTPONED, but it convened to
        # adjourn itself and has minutes saying so.
        ("25 Mar 2025 8.00 pm", "Agenda, Minutes, POSTPONED; Special"),
        ("8 Apr 2025 6.00 pm", "Agenda, Minutes"),
    )
    found = _Scraper()._parse_listing(html, 2025)
    assert [m["date"] for m in found] == ["2025-03-25", "2025-04-08"]


def test_every_listing_failing_is_an_error_not_an_empty_council():
    """An empty list reaches production as a council that ran fine with no
    meetings. If no listing could be fetched at all, say so."""

    class Failing:
        def fetch_with_requests(self, url, **kwargs):
            raise RuntimeError("simulated WAF block")

    scraper = _Scraper()
    scraper.years_filter = [2025]
    scraper.fetcher = Failing()
    with pytest.raises(RuntimeError, match="listing requests failed"):
        ModernGovScraper.scraper(scraper)
