"""City of Marion.

A SimpleGov archive (see `aus_council_scrapers/craft.py`): a
`table.table--agendasMinutes`, twenty rows a page, each row holding the
meeting date, a committee code and its Agenda / Minute / Audio links
directly. Upcoming meetings are listed too, with "No attachments" until
their agenda goes up.

The committee column is an abbreviation—`GC`, `CAP`—so the meeting type
is looked up in `_COMMITTEES`. The alternative, one filtered query per
committee, would know the names for free but cost a page load for each of
nineteen committees every night, most of them long disbanded.
"""

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.craft import (
    CraftArchiveScraper,
    CraftMeeting,
    clean_text,
    document_links,
    parse_listing_date,
)

# The codes Marion prints, against the names its own committee filter uses.
# The codes are the prefix of each document's filename (GC251209-Final-Agenda),
# which is where the less obvious ones were confirmed.
_COMMITTEES = {
    "GC": "General Council",
    "SGC": "Special General Council",
    "CAP": "Council Assessment Panel",
    "FAC": "Finance and Audit Committee",
    "RSC": "Review and Selection Committee",
    "CYG": "Community & Youth Grants Committee",
    "IEC": "Infrastructure and Environment Committee",
    # Committees since disbanded, still in the archive back to 2020.
    "PDC": "Planning and Development Committee",
    "UPC": "Urban Planning Committee",
    "ASC": "Asset and Sustainability Committee",
    "ISC": "Infrastructure and Strategy Committee",
    "IC": "Infrastructure Committee",
    "EC": "Environment Committee",
}


@register_scraper
class MarionScraper(CraftArchiveScraper):
    listing_url = "https://www.marion.sa.gov.au/about-council/council-meetings/archive"

    # From a GitHub-hosted runner, plain requests get the AWS WAF challenge
    # whatever the User-Agent; headless Chrome passes unmodified.

    def __init__(self):
        super().__init__("marion", "SA", "https://www.marion.sa.gov.au")
        self._unknown_codes: set[str] = set()

    def _committee(self, code: str) -> str:
        name = _COMMITTEES.get(code.upper())
        if name:
            return name
        if code not in self._unknown_codes:
            # Better a bare code than a dropped meeting, but it should not
            # stay that way unnoticed.
            self._unknown_codes.add(code)
            self.logger.warning(
                f"Unknown Marion committee code {code!r}; add it to _COMMITTEES"
            )
        return code

    def parse_meetings(self, soup: BeautifulSoup) -> list[CraftMeeting]:
        meetings = []
        for row in soup.select("table.table--agendasMinutes tbody tr"):
            when = clean_text(row.select_one('[data-column="Meeting Date"]'))
            date = parse_listing_date(when)
            if date is None:
                self.logger.warning(f"No date in listing row: {when!r}")
                continue
            code = clean_text(row.select_one('[data-column="Committee"]'))
            meetings.append(
                CraftMeeting(
                    name=self._committee(code),
                    date=date,
                    links=document_links(row, self.listing_url),
                )
            )
        return meetings
