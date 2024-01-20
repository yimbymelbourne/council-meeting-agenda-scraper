import re
from typing import List, TypedDict 

# Add keys here as needed
class Regexes(TypedDict):
    keyword_matches: List[str]

class RegexResults(TypedDict):
    keyword_matches: dict[str, int]

defaults = Regexes({
  'keyword_matches': [
    'dwellings', 
    'heritage',
  ]
})