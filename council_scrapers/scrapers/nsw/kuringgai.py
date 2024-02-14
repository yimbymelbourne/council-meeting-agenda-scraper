import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)


from council_scrapers.base import register_scraper
from infocouncil_scraper import InfoCouncilScraper


@register_scraper
class KuRingGaiScraper(InfoCouncilScraper):
    def __init__(self):
        council = "kuringgai"
        state = "NSW"
        base_url = "http://www.krg.nsw.gov.au/"
        infocouncil_url = "https://eservices.kmc.nsw.gov.au/Infocouncil.Web/"
        super().__init__(council, state, base_url, infocouncil_url)


if __name__ == "__main__":
    scraper = KuRingGaiScraper()
