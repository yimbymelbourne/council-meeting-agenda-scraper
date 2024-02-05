import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from base_scraper import register_scraper
from infocouncil_scraper import InfoCouncilScraper


@register_scraper
class WhitehorseScraper(InfoCouncilScraper):
    def __init__(self):
        council = "whitehorse"
        state = "VIC"
        base_url = "https://www.whitehorse.vic.gov.au/"
        infocouncil_url = "https://whitehorse.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)


if __name__ == "__main__":
    scraper = WhitehorseScraper()
    scraper.scraper()
