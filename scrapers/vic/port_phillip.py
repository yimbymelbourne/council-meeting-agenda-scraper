import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from infocouncil_scraper import InfoCouncilScraper
from base_scraper import register_scraper

@register_scraper
class PortPhilipScraper(InfoCouncilScraper):
    def __init__(self):
        council = "port_philip"
        state = "VIC"
        base_url = "https://www.portphillip.vic.gov.au/"
        infocouncil_url = "https://portphillip.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)


if __name__ == "__main__":
    scraper = PortPhilipScraper()
    scraper.scraper()
