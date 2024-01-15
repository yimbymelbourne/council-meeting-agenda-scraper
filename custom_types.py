from typing import Callable
from regexes import Regexes

class Council:
    def __init__(self, name: str, scraper: Callable[[],str|None], regexes: Regexes):
        self.name = name
        self.scraper = scraper
        self.regexes = regexes