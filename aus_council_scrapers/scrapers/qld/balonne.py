import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class BalonneScraper(ResolveScraper):
    # Balonne's Minutes-and-Agendas page holds only a link to its CivicClerk
    # portal (balonne.civicclerk.com.au, the same tenant), whose record
    # starts with the 16 November 2023 Ordinary meeting. No older papers are
    # linked from the council's website.
    tenant = "balonne"

    # Every type but "Supplementary Agenda". Balonne files each
    # supplementary agenda as an event of its own, dated with the meeting it
    # adds to ("Supplementary May Ordinary Council Meeting", 23 May 2024),
    # so kept it would be a second Ordinary meeting that day whose agenda is
    # the supplementary paper. The Ordinary event carries the meeting's own
    # agenda and its minutes.
    meeting_types = re.compile(
        r"^(Ordinary Council Meeting|Special Council Meeting|Special Budget Meeting)$"
    )

    def __init__(self):
        super().__init__("balonne", "QLD")
