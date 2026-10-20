import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class CookScraper(ResolveScraper):
    # Cook Shire's agendas-and-minutes page frames the tenant's /web/ portal
    # and says papers from January 2022 are on Resolve and older ones are
    # available on request, so the tenant is the council's whole online
    # record. Through 2022 the council uploaded each meeting's papers as a
    # packet and minutes with no bare agenda, so those agendas are packets,
    # which the base class prefers anyway.
    tenant = "cook"

    # The tenant's only two types. Cook files most special meetings under
    # the ordinary type ("Special Council Meeting - 15 October 2026" is an
    # Ordinary Council Meeting event), and the base class names those from
    # the "Special" in the event name. Naming the types keeps a committee
    # the council starts publishing here from adding a detail call per
    # meeting to the nightly run unasked.
    meeting_types = re.compile(r"^(Ordinary|Special) Council Meeting$")

    def __init__(self):
        super().__init__("cook", "QLD")
