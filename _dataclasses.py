from dataclasses import dataclass
from typing import Callable, Optional
from regexes import Regexes

@dataclass
class ScraperReturn:
    """Designates what a scraper should return.\n
    If a given item in the scraper is None, it will be skipped.
    """
    name: str
    date: str
    time: str
    webpage_url: str
    download_url: str

@dataclass
class Council:
    """Represents a council with a scraper and regexes.\n
    The scraper is a function that returns a ScraperReturn instance or None.
    The regexes are used to parse the data in the PDF scraped by the scraper.
    The results of this parsing are stored in the results attribute.
    """
    name: str
    scraper: Callable[[], Optional[ScraperReturn]]
    regexes: Optional[Regexes] = None
    results: Optional[ScraperReturn] = None

    def run_scraper(self):
        """Runs the scraper and stores the results."""
        self.results = self.scraper()