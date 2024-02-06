import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from base_scraper import register_scraper
from infocouncil_scraper import InfoCouncilScraper


@register_scraper
class BaysideNSWScraper(InfoCouncilScraper):
    def __init__(self):
        council = "bayside"
        state = "NSW"
        base_url = "https://bayside.nsw.gov.au"
        infocouncil_url = "https://infoweb.bayside.nsw.gov.au/?committee=1"
        super().__init__(council, state, base_url, infocouncil_url)


if __name__ == "__main__":
    scraper = BaysideNSWScraper()
    scraper.scraper()
