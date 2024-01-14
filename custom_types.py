from typing import TypedDict, Callable

class Council(TypedDict):
  name: str # Name of council (e.g. Maribyrnong; Merri-bek)
  scraper: Callable # Function that returns a link to the agenda
  custom_regexes: dict # Dictionary of regex types and regexes
  
  