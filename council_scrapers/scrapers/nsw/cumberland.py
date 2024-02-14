import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from infocouncil_scraper import InfoCouncilScraper
from council_scrapers.base import register_scraper


@register_scraper
class CumberlandScraper(InfoCouncilScraper):
    def __init__(self):
        council = "cumberland"
        state = "NSW"
        base_url = "https://www.cumberland.nsw.gov.au/"
        infocouncil_url = "https://cumberland.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)


if __name__ == "__main__":
    scraper = CumberlandScraper()
    scraper.scraper()
