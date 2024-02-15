import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from council_scrapers.base import InfoCouncilScraper
from council_scrapers.base import register_scraper


@register_scraper
class HornsbyScraper(InfoCouncilScraper):
    def __init__(self):
        council = "hornsby"
        state = "NSW"
        base_url = "https://www.hornsby.nsw.gov.au/"
        infocouncil_url = "https://businesspapers.hornsby.nsw.gov.au/"
        super().__init__(council, state, base_url, infocouncil_url)


if __name__ == "__main__":
    scraper = HornsbyScraper()
    scraper.scraper()
