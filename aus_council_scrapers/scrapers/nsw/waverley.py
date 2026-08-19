import datetime
import re

from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)

# Waverley is the only InfoCouncil site that renders its meeting dates as
# DD/MM/YYYY rather than "18 Aug 2026", so the shared DATE_REGEX never matches.
WAVERLEY_DATE_REGEX = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


@register_scraper
class WaverleyScraper(InfoCouncilScraper):
    def __init__(self):
        council = "waverley"
        state = "NSW"
        base_url = "https://www.waverley.nsw.gov.au/"
        infocouncil_url = "https://waverley.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)
        self.default_location = "Cnr Paul Street and Bondi Road, Bondi Junction"
        self.default_time = "7 PM"
        self.date_regex = WAVERLEY_DATE_REGEX

    def scraper(self) -> list[ScraperReturn]:
        results = super().scraper()
        for result in results:
            result.date = self._normalise_date(result.date)
        return results

    @staticmethod
    def _normalise_date(date: str) -> str:
        """Rewrite a DD/MM/YYYY date as ISO.

        Waverley's dates are day-first, but `cleaned_date` parses them
        month-first, which would read 04/08/2026 as 8 April.
        """
        match = WAVERLEY_DATE_REGEX.fullmatch(date) if date else None
        if not match:
            return date

        day, month, year = (int(part) for part in match.groups())
        try:
            return datetime.date(year, month, day).isoformat()
        except ValueError:
            return date
