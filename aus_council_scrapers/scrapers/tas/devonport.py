import datetime
import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.wpfd import WPFDListing, WPFileDownloadScraper, find_date

# Devonport City Council. The current year is on the council-meetings page,
# one WP File Download category per month ("september-2026"), so the meeting
# day comes from the files ("Agenda – Council Meeting – 28 September 2026").
# Earlier years (from August 2019) are on the archive page, one category per
# meeting; 2016–2018 there are lazy-loaded subcategories, before EARLIEST_YEAR.
#
# The same council-meetings page lists the year's meeting dates with their
# start time ("Monday, 26 October 2026 | 5:30pm"), so the current year's
# Council meetings carry it. Earlier years publish no time outside the PDFs.
#
# The Planning Authority Committee, the council sitting as planning
# authority, has its own page with its whole history (2016 on). Nothing on
# the site links to it any more: it sits at a retired "council-meetings-old"
# path, and the link on the current council-meetings page
# (/section-23-committees/planning-authority-committee/) is a 404. The council
# still uploads to it, so it is read; if it moves, the 404 fails the scrape,
# which is the signal to find its new home.
#
# A production year is two requests: the current page and the PAC page.
# Cloudflare fronts the site (server: cloudflare, CF-Ray); no challenge from
# a home IP. robots.txt disallows only search parameters.

_CURRENT_PAGE = "https://www.devonport.tas.gov.au/council/council-meetings/"
_DATE_AND_TIME = re.compile(
    r"^(?:[a-z]+,?\s+)?(\d{1,2}\s+[a-z]+\s+20\d\d)\s*\|\s*(\d{1,2}(?:[:.]\d\d)?\s*[ap]\.?m\.?)$",
    re.IGNORECASE,
)


@register_scraper
class DevonportScraper(WPFileDownloadScraper):
    listings = (
        WPFDListing(_CURRENT_PAGE),
        WPFDListing(
            "https://www.devonport.tas.gov.au/council/agendas-and-minutes-archive/",
            archive=True,
        ),
        WPFDListing(
            "https://www.devonport.tas.gov.au/council/council-meetings-old/planning-authority-committee/",
            default_name="Planning Authority Committee",
        ),
    )

    def __init__(self):
        super().__init__("devonport", "TAS", "https://www.devonport.tas.gov.au")

    def listing_times(
        self, listing: WPFDListing, soup: BeautifulSoup
    ) -> dict[datetime.date, str]:
        if listing.url != _CURRENT_PAGE:
            return {}
        times = {}
        for item in soup.select("li"):
            m = _DATE_AND_TIME.match(" ".join(item.get_text(" ", strip=True).split()))
            if m and (date := find_date(m.group(1))):
                times[date] = m.group(2)
        return times
