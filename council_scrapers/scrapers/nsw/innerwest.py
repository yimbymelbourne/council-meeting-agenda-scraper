import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from council_scrapers.base import register_scraper
from infocouncil_scraper import InfoCouncilScraper


@register_scraper
class InnerWestScraper(InfoCouncilScraper):
    def __init__(self):
        council = "inner_west"
        state = "NSW"
        base_url = "https://innerwest.infocouncil.biz"
        infocouncil_url = "https://innerwest.infocouncil.biz/Default.aspx"
        super().__init__(council, state, base_url, infocouncil_url)


if __name__ == "__main__":
    scraper = InnerWestScraper()
    scraper.scraper()
