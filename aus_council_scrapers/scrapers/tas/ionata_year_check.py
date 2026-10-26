"""Fail loudly when an Ionata archive lists nothing for a year it covers.

`IonataMeetingsScraper.scraper()` only warns when a listing comes back with
no cards, and council-alerts records a returned `[]` as a successful scrape
with no meetings. An empty page is exactly what a changed theme, or a WAF
serving a placeholder, looks like. Clarence, Glenorchy and Sorell inherit
that behaviour from the base; West Tamar and Glamorgan Spring Bay add this
check on top, because each knows the first year its archive holds.

The check belongs in `aus_council_scrapers/ionata.py` itself, with the first
year as a class attribute; it lives here until that base module can change.
"""

from __future__ import annotations

import datetime

from aus_council_scrapers import clock
from aus_council_scrapers.base import ScraperReturn

# A council that meets monthly has had two or three meetings by the end of
# March. Before then an empty year can be a quiet January, so it only warns
# (in the base class).
_GRACE = datetime.timedelta(days=90)


class IonataYearCheck:
    """Mixin for an `IonataMeetingsScraper` subclass. Set `archive_starts`."""

    # The first year the archive's `f_year` filter returns cards. Earlier
    # years are empty by the council's doing and are not checked.
    archive_starts: int

    def scraper(self) -> list[ScraperReturn]:
        results = super().scraper()
        listed = {int(r.date[:4]) for r in results}
        today = clock.today()
        missing = [
            year
            for year in self._wanted_years()
            if year >= self.archive_starts
            and year not in listed
            and today - datetime.date(year, 1, 1) > _GRACE
        ]
        if missing:
            raise RuntimeError(
                f"{self.council_name}: no meetings with documents at "
                f"{self.listing_url} for {missing}, years the archive covers; "
                f"the listing markup has probably changed or the page was blocked"
            )
        return results
