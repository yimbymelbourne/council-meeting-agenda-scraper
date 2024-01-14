from typing import TypedDict, Callable

class Council(TypedDict):
  council: str
  regex_dict: dict
  scraper: Callable
  