import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.walkerdesigns import (
    WalkerDesignsDocument,
    WalkerDesignsMeetingsScraper,
    WalkerDesignsRow,
    find_date,
)

# Dorset Council. The same agency's other template: no table, but a page per
# year of download cards, agendas and minutes on separate pages, each card's
# heading naming the document and the meeting's date ("Agenda and Attachments
# 17 November 2025", "Special Meeting Minutes 6 May 2025"). The agenda PDF
# includes its attachments. The two index pages link each year's page; the
# slugs are not regular (2021 and 2022 are "-agendas-and-attachments", later
# years "-agenda-and-attachments"), so they are read rather than built. The
# base class pairs each agenda with the minutes of the same date and type.
#
# Pages start at 2021. Separate cards for single items ("Item 152 - 12. Code
# Overlays", a late item) sit among the agendas and are left out. A meeting
# appears only once its agenda is up.
#
# A production year is four requests: the two indexes and the year's two
# pages. Apache, no CDN in front. robots.txt disallows /assets/, /manager/
# and other CMS paths, none of which this reads.

_INDEXES = (
    ("agenda", "https://www.dorset.tas.gov.au/council-meeting-agendas"),
    ("minutes", "https://www.dorset.tas.gov.au/council-meeting-minutes"),
)
_YEAR = re.compile(r"^(20\d\d)\b")
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)


@register_scraper
class DorsetScraper(WalkerDesignsMeetingsScraper):
    earliest_year = 2021

    def __init__(self):
        super().__init__("dorset", "TAS", "https://www.dorset.tas.gov.au")

    def listing_rows(self, wanted: set[int]) -> list[WalkerDesignsRow]:
        rows = []
        for kind, index_url in _INDEXES:
            index = BeautifulSoup(
                self.fetcher.fetch_with_requests(index_url), "html.parser"
            )
            year_pages = {}
            for link in index.select("a.child-listing[href]"):
                m = _YEAR.match(" ".join(link.get_text(" ", strip=True).split()))
                if m:
                    year_pages[int(m.group(1))] = link["href"].strip()
            if not year_pages:
                # The index is the only way to the year pages. An index with
                # none means the site changed, not that there are no meetings.
                raise ValueError(f"dorset: no year pages linked from {index_url}")
            for year in sorted(wanted & set(year_pages)):
                rows.extend(self._year_page(kind, year_pages[year]))
        return rows

    def _year_page(self, kind: str, url: str) -> list[WalkerDesignsRow]:
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        cards = soup.select("a.download-item[href]")
        if not cards:
            self.logger.warning(f"dorset: no documents on {url}")
        rows = []
        for card in cards:
            heading = card.find("h4")
            title = " ".join(
                (heading or card).get_text(" ", strip=True).split()
            )
            doc = WalkerDesignsDocument(url=card["href"].strip(), title=title)
            # The heading's date, not the file name's: the 12 May 2023
            # special meeting's minutes are filed as "...-12-June-2023.pdf".
            date = find_date(title) or doc.own_date
            if date is None:
                self.logger.warning(f"dorset: {title!r} on {url} names no date")
                continue
            row = WalkerDesignsRow(
                date=date,
                name=(
                    "Special Council Meeting"
                    if _SPECIAL.search(title)
                    else "Ordinary Council Meeting"
                ),
                webpage_url=url,
            )
            (row.agendas if kind == "agenda" else row.minutes).append(doc)
            rows.append(row)
        return rows
