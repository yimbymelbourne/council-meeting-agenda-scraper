import re

from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_shires import (
    ShireCouncilConnectScraper,
)

# The shire labels a meeting's papers "OCM Agenda - 25 October 2023" and
# "SCM Minutes - ...". A Special meeting held the same day as an Ordinary one
# can be filed on the Ordinary meeting's page, under the same Agenda and
# Minutes headings (25 October 2023, at noon before the 2 pm Ordinary
# meeting; both SCM papers read). A reference to a Special meeting among the
# Ordinary meeting's reports ("10.2 a) SCM Minutes - 7 August 2026", under
# "Documents") is numbered, so it does not match.
_SPECIAL_PAPER = re.compile(r"^(?:View\s+)?SCM\b", re.IGNORECASE)
_ORDINARY_PAPER = re.compile(r"^(?:View\s+)?OCM\b", re.IGNORECASE)
_PAPERS_GROUP = re.compile(r"agenda|minut", re.IGNORECASE)
_LABEL_DATE = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:january|february|march|april|may|june|"
    r"july|august|september|october|november|december)\s+\d{4}\b",
    re.IGNORECASE,
)


@register_scraper
class JerramungupScraper(ShireCouncilConnectScraper):
    """Shire of Jerramungup—documents on each meeting's own page.

    Council meetings only; the one other type is the annual electors'
    meeting, left out because each meeting costs a request.

    Some agendas are posted only as Word files (29 July 2026), which the
    base skips, so those meetings carry minutes only.

    A Special meeting with no page of its own, whose agenda and minutes sit
    on an Ordinary meeting's page beside the Ordinary ones (25 October
    2023), is split out as a record of its own: the base reads one meeting
    per page, and left to itself it would pick whichever papers were listed
    first. The Special record has no time, because the page's time is the
    Ordinary meeting's.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 24 s for
    # 13 requests (the type listings, one per Council meeting of the year
    # and the upcoming page). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 24

    def __init__(self):
        super().__init__("jerramungup", "WA", "https://www.jerramungup.wa.gov.au")
        self._special_papers: dict[str, list] = {}

    def _detail_links(self, soup, page_url):
        links = super()._detail_links(soup, page_url)
        if "/ordinary-council-meeting/" not in page_url:
            return links
        papers = [link for link in links if _PAPERS_GROUP.search(link[0] or "")]
        special = [link for link in papers if _SPECIAL_PAPER.match(link[1])]
        if not special or not any(_ORDINARY_PAPER.match(l[1]) for l in papers):
            return links
        self._special_papers[page_url] = special
        return [link for link in links if link not in special]

    def scraper(self):
        self._special_papers = {}
        results = super().scraper()
        for page_url, links in self._special_papers.items():
            ordinary = next((r for r in results if r.webpage_url == page_url), None)
            if ordinary is None:
                continue
            agenda_url, minutes_url = self._pick_documents(
                [
                    (group, re.sub(r"^View\s+", "", label), url)
                    for group, label, url in links
                ]
            )
            if not (agenda_url or minutes_url):
                continue
            # The papers' own date, in case the Special was not held on the
            # Ordinary meeting's day; the page's date otherwise.
            label_date = next(
                (m.group() for _, l, _ in links if (m := _LABEL_DATE.search(l))), None
            )
            date = (
                parse_date(label_date).date().isoformat()
                if label_date
                else ordinary.date
            )
            if int(date[:4]) not in self._wanted_years():
                continue
            results.insert(
                results.index(ordinary) + 1,
                ScraperReturn(
                    name="Special Council Meeting",
                    date=date,
                    time=None,
                    webpage_url=page_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                    location=ordinary.location,
                ),
            )
        return results
