from typing import Callable
from regexes import Regexes

class ScraperReturn:
    def __init__(self, name: str, date: str, time: str, webpage_url: str, download_url: str):
        self.name = name
        self.date = date
        self.time = time
        self.webpage_url = webpage_url
        self.download_url = download_url

class Council:
    def __init__(self, name: str, scraper: Callable[[],ScraperReturn|None], regexes: Regexes):
        self.name = name
        self.scraper = scraper
        self.regexes = regexes