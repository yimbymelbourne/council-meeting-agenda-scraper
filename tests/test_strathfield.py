"""
Unit tests for the Strathfield NSW scraper.
"""
import json
import pytest

from aus_council_scrapers.scrapers.nsw.strathfield import StrathfieldNSWScraper

# Real OCServiceHandler response format: selenium returns a page whose <pre> body is
# JSON with an "html" field containing HTML-escaped meeting details.

_AGENDA_ONLY_RESPONSE = """<html><body><pre>{}</pre></body></html>""".format(
    json.dumps(
        {
            "_response_status": {"messages": [], "status": "Okay"},
            "html": (
                '<div class="meeting-container">'
                "<p>16 December 2025 Extraordinary Council Meeting</p>"
                '<div class="meeting-attachments">'
                '<ul class="related-information-list">'
                '<li><a href="/files/assets/public/v/2/council/council-meetings/2025/'
                'extraordinary-council-meeting-16-december-2025-agenda.pdf">Agenda</a></li>'
                "</ul></div></div>"
            ),
        }
    ).replace("/", "\\/")
)

_AGENDA_AND_MINUTES_RESPONSE = """<html><body><pre>{}</pre></body></html>""".format(
    json.dumps(
        {
            "_response_status": {"messages": [], "status": "Okay"},
            "html": (
                '<div class="meeting-container">'
                "<p>25 November 2025 Ordinary Council Meeting</p>"
                '<div class="meeting-attachments">'
                '<ul class="related-information-list">'
                '<li><a href="/files/assets/public/v/1/council/council-meetings/2025/'
                'ordinary-council-meeting-25-november-2025-agenda.pdf">Agenda</a></li>'
                '<li><a href="/files/assets/public/v/1/council/council-meetings/2025/'
                'ordinary-council-meeting-25-november-2025-minutes.pdf">Minutes</a></li>'
                "</ul></div></div>"
            ),
        }
    ).replace("/", "\\/")
)

_NO_PDF_RESPONSE = """<html><body><pre>{}</pre></body></html>""".format(
    json.dumps(
        {
            "_response_status": {"messages": [], "status": "Okay"},
            "html": "<div class='meeting-container'><p>No documents available</p></div>",
        }
    )
)

_INDEX_PAGE_HTML = """
<html><body>
<a class="accordion-trigger minutes-trigger ajax-trigger"
   data-cvid="aaaa1111-0000-0000-0000-000000000001">
  <span class="minutes-date">16 December 2025</span>
  <span class="meeting-type">Extraordinary Meeting</span>
</a>
<a class="accordion-trigger minutes-trigger ajax-trigger"
   data-cvid="bbbb2222-0000-0000-0000-000000000002">
  <span class="minutes-date">25 November 2025</span>
  <span class="meeting-type">Ordinary Meeting</span>
</a>
<a class="accordion-trigger minutes-trigger ajax-trigger"
   data-cvid="cccc3333-0000-0000-0000-000000000003">
  <span class="minutes-date">01 January 2019</span>
  <span class="meeting-type">Ordinary Meeting</span>
</a>
</body></html>
"""


@pytest.fixture
def scraper():
    return StrathfieldNSWScraper()


class TestExtractUrls:
    def test_agenda_only(self, scraper):
        agenda_url, minutes_url = scraper._extract_urls_from_details(_AGENDA_ONLY_RESPONSE)
        assert agenda_url == (
            "https://www.strathfield.nsw.gov.au/files/assets/public/v/2/council/"
            "council-meetings/2025/extraordinary-council-meeting-16-december-2025-agenda.pdf"
        )
        assert minutes_url is None

    def test_agenda_and_minutes(self, scraper):
        agenda_url, minutes_url = scraper._extract_urls_from_details(
            _AGENDA_AND_MINUTES_RESPONSE
        )
        assert agenda_url is not None
        assert "agenda" in agenda_url
        assert minutes_url is not None
        assert "minutes" in minutes_url

    def test_no_pdfs_yields_no_urls(self, scraper):
        """A meeting with no published documents is still a meeting.

        This used to raise, which the caller caught and turned into a dropped
        row — so two 2020 meetings Strathfield never published papers for went
        missing from the output rather than appearing without documents.
        """
        assert scraper._extract_urls_from_details(_NO_PDF_RESPONSE) == (None, None)

    def test_relative_url_resolved_to_absolute(self, scraper):
        agenda_url, _ = scraper._extract_urls_from_details(_AGENDA_ONLY_RESPONSE)
        assert agenda_url.startswith("https://www.strathfield.nsw.gov.au/")


class TestExtractMeetingStubs:
    def test_extracts_all_meetings(self, scraper):
        stubs = scraper._extract_meeting_stubs(_INDEX_PAGE_HTML)
        assert len(stubs) == 3

    def test_meeting_fields(self, scraper):
        stubs = scraper._extract_meeting_stubs(_INDEX_PAGE_HTML)
        assert stubs[0].cvid == "aaaa1111-0000-0000-0000-000000000001"
        assert stubs[0].date == "16 December 2025"
        assert stubs[0].meeting_type == "Extraordinary Meeting"

    def test_empty_html_returns_empty(self, scraper):
        stubs = scraper._extract_meeting_stubs("<html><body></body></html>")
        assert stubs == []


class TestYearsFilter:
    def test_respects_years_filter(self, scraper, monkeypatch):
        """Scraper stops paginating once meetings fall below min year in filter."""
        scraper.years_filter = [2025]

        pages = {
            "https://www.strathfield.nsw.gov.au/Council/Council-Meetings": _INDEX_PAGE_HTML,
        }
        details = {
            "aaaa1111-0000-0000-0000-000000000001": _AGENDA_ONLY_RESPONSE,
            "bbbb2222-0000-0000-0000-000000000002": _AGENDA_AND_MINUTES_RESPONSE,
        }

        class MockFetcher:
            def fetch_with_selenium(self, url):
                if url in pages:
                    return pages[url]
                # Extract cvid from url for OCServiceHandler calls
                for cvid, html in details.items():
                    if cvid in url:
                        return html
                return "<html><body></body></html>"

        scraper.fetcher = MockFetcher()
        results = scraper.scraper()

        # Only 2025 meetings: 16 Dec and 25 Nov (01 Jan 2019 below EARLIEST_YEAR stops it)
        dates = [r.date for r in results]
        assert all("2025" in d for d in dates)

    def test_years_filter_excludes_non_matching(self, scraper):
        """With years_filter=[2025], meetings from other years are skipped."""
        scraper.years_filter = [2025]

        class MockFetcher:
            def fetch_with_selenium(self, url):
                if "Council-Meetings" in url and "pageindex" not in url:
                    return _INDEX_PAGE_HTML
                return "<html><body></body></html>"

        scraper.fetcher = MockFetcher()
        results = scraper.scraper()

        # The 2019 meeting is below EARLIEST_YEAR, so pagination stops there. The
        # two 2025 meetings have no documents in this mock, which is not an error
        # but is not emittable either — downstream keys a meeting on its document
        # URL — so they are skipped and nothing is returned.
        assert results == []


_ALL_CURRENT_YEAR_PAGE = """
<html><body>
<a class="accordion-trigger minutes-trigger ajax-trigger"
   data-cvid="aaaa1111-0000-0000-0000-000000000001">
  <span class="minutes-date">16 December 2025</span>
  <span class="meeting-type">Extraordinary Meeting</span>
</a>
<a class="accordion-trigger minutes-trigger ajax-trigger"
   data-cvid="bbbb2222-0000-0000-0000-000000000002">
  <span class="minutes-date">25 November 2025</span>
  <span class="meeting-type">Ordinary Meeting</span>
</a>
</body></html>
"""


class TestFailuresAreNotSilent:
    """A short run must never be reported as a complete one.

    On 2026-09-01 production returned page one's ten meetings for 2026 and
    logged "10 meetings" for a year holding fifteen: the second page fetch
    failed and `except Exception: break` presented the truncation as the end
    of the listing. Only an empty page ends pagination; every other failure
    has to reach the caller.
    """

    def _fetcher(self, fail_on):
        class MockFetcher:
            def fetch_with_selenium(self, url):
                if fail_on(url):
                    raise RuntimeError("simulated fetch failure")
                if "OCServiceHandler" in url:
                    return _AGENDA_ONLY_RESPONSE
                if "pageindex" in url:
                    return "<html><body></body></html>"
                return _ALL_CURRENT_YEAR_PAGE

        return MockFetcher()

    def test_page_fetch_failure_propagates(self, scraper):
        scraper.years_filter = [2025]
        scraper.fetcher = self._fetcher(lambda url: "pageindex=2" in url)

        with pytest.raises(RuntimeError, match="simulated fetch failure"):
            scraper.scraper()

    def test_detail_fetch_failure_propagates(self, scraper):
        scraper.years_filter = [2025]
        scraper.fetcher = self._fetcher(lambda url: "OCServiceHandler" in url)

        with pytest.raises(RuntimeError, match="simulated fetch failure"):
            scraper.scraper()

    def test_empty_page_still_ends_pagination(self, scraper):
        """The one legitimate stop condition keeps working."""
        scraper.years_filter = [2025]
        scraper.fetcher = self._fetcher(lambda url: False)

        results = scraper.scraper()

        assert [r.date for r in results] == ["16 December 2025", "25 November 2025"]

    def test_undocumented_meeting_is_skipped_without_losing_its_siblings(
        self, scraper
    ):
        """A meeting with no papers is skipped, not treated as a failure.

        `ingestCouncils` keys a meeting on its document URL and discards rows
        that have none, so emitting one is pointless. Skipping it must not cost
        the meetings around it, which is what an abort would do.
        """
        scraper.years_filter = [2025]

        class MockFetcher:
            def fetch_with_selenium(self, url):
                if "aaaa1111" in url:
                    return _NO_PDF_RESPONSE
                if "OCServiceHandler" in url:
                    return _AGENDA_AND_MINUTES_RESPONSE
                if "pageindex" in url:
                    return "<html><body></body></html>"
                return _ALL_CURRENT_YEAR_PAGE

        scraper.fetcher = MockFetcher()
        results = scraper.scraper()

        assert [r.date for r in results] == ["25 November 2025"]
