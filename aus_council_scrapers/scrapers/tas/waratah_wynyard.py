from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.wpfd import WPFDListing, WPFileDownloadScraper

# Waratah-Wynyard Council. One page holds every meeting from January 2021,
# one WP File Download category per meeting ("meeting-19-october-2026",
# "special-5-feb-2025", "annual-general-meeting-15-jan-2024"), so a
# production year is one request.
#
# The files are hand-titled and the category is usually the better witness to
# the date: "Council Muinutes 20 July 2027-PUBLIC" sits in the 20 July 2026
# meeting, and AGM agendas are named for the day they were issued ("2025 -
# AGM Agenda 27 10 25" in the 5 November 2025 AGM). The base class's vote
# settles both. It also leaves off the copy of the 16 February 2026 agenda
# filed under 20 October 2025, and the 2021 AGM minutes filed under the 2022
# AGM, since both of those meetings have categories of their own.
#
# nginx, no CDN; robots.txt disallows nothing.


@register_scraper
class WaratahWynyardScraper(WPFileDownloadScraper):
    listings = (
        WPFDListing("https://www.warwyn.tas.gov.au/our-council/agendas-minutes/"),
    )

    def __init__(self):
        super().__init__("waratah_wynyard", "TAS", "https://www.warwyn.tas.gov.au")
