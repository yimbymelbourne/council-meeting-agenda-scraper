import re

from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)

# InfoCouncil names an extra meeting of a committee "Extra <committee>".
_EXTRA = re.compile(r"^Extra\s+")


@register_scraper
class CootamundraGundagaiScraper(InfoCouncilScraper):
    # Self-hosted InfoCouncil, framed by the council's business papers page.
    # Every body is kept (Council and, from 2026, the Demerger Transition
    # Committee): the grid is one request a year whatever it lists.
    #
    # The council is splitting into Cootamundra and Gundagai councils, so
    # this host and slug may change; worth re-checking in 2027.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "cootamundra_gundagai",
            "NSW",
            "https://www.cgrc.nsw.gov.au",
            # The Default.aspx form, not the bare root: robots.txt here is
            # `Disallow: /` with `Allow: /Default.aspx` (and `/$`), so
            # `/?year=2026` is disallowed and `/Default.aspx?year=2026` is
            # not. The documents' `RedirectToDoc.aspx` is allowed too.
            "https://businesspapers.cgrc.nsw.gov.au/Default.aspx",
        )

    def scraper(self) -> list[ScraperReturn]:
        results = super().scraper()
        for record in results:
            if record.name:
                record.name = _EXTRA.sub("Extraordinary ", record.name)
        return results
