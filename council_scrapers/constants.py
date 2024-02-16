import re

COUNCIL_HOUSING_REGEX = [
    "dwellings",
    "heritage",
]
TIME_REGEX = re.compile(r"\d+:\d+\s?[apmAPM]+")
DATE_REGEX = re.compile(
    r"\d{1,2}\s(?:January|February|March|April|May|June|July|August|September|October|November|December)\s\d{4}"
)
