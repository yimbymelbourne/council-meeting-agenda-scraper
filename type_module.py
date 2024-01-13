from typing import TypedDict, Callable

class Council(TypedDict):
  council: str
  regex_list: list
  scraper: Callable
  