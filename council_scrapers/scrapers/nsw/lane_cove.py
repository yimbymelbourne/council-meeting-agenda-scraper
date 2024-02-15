import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from council_scrapers.base import InfoCouncilScraper
from council_scrapers.base import register_scraper


@register_scraper
class LaneCoveScraper(InfoCouncilScraper):
    def __init__(self):
        council = "lane_cove"
        state = "NSW"
        base_url = "https://lanecove.infocouncil.biz"
        infocouncil_url = "https://lanecove.infocouncil.biz"
        super().__init__(council, state, base_url, infocouncil_url)


if __name__ == "__main__":
    scraper = LaneCoveScraper()
    scraper.scraper()
