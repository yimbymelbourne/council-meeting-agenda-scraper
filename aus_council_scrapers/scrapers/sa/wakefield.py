"""Wakefield Regional Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The meetings
index (/ourcouncil/meetings-and-agendas) carries no listing of its own; each
page under it lists one committee, so the council-meetings page and the Mid
North Regional Assessment Panel's page are read. About a quarter of the
council page's documents are meeting audio, which the base class never
treats as an agenda or minutes.

The panel's papers are often filed under a date that is not the meeting's,
so they are dated from their titles and file names; see
`lgasa_panel_dates`.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper, _Listed
from aus_council_scrapers.scrapers.sa.lgasa_panel_dates import dated_as_stated

_PANEL_PAGE = (
    "https://www.wrc.sa.gov.au/ourcouncil/meetings-and-agendas/"
    "mid-north-regional-assessment-panel"
)


@register_scraper
class WakefieldScraper(LGASAFunnelbackScraper):
    # Council and the Mid North Regional Assessment Panel, which decides
    # development applications for Wakefield, Goyder and Clare and Gilbert
    # Valleys. Goyder's site does not publish the panel and no Clare and
    # Gilbert Valleys scraper exists yet, so this is the only scraper that
    # reads it. The audit, infrastructure and grants committees each have a
    # page of their own and are not read: each would cost one more Selenium
    # page and a 20 s crawl delay a night.
    listing_urls = (
        "https://www.wrc.sa.gov.au/ourcouncil/meetings-and-agendas/councilmeetings",
        _PANEL_PAGE,
    )

    # One production year, measured 20 Oct 2026 from a home IP: 26 s (two
    # Selenium page loads and one 20 s crawl delay between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 26

    def __init__(self):
        super().__init__("wakefield", "SA", "https://www.wrc.sa.gov.au")

    def _listing_documents(self, listing_url: str, earliest_year: int) -> list[_Listed]:
        documents = super()._listing_documents(listing_url, earliest_year)
        if listing_url != _PANEL_PAGE:
            return documents
        return [dated_as_stated(listed) for listed in documents]
