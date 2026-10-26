import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class GoulburnMulwareeScraper(ResolveScraper):
    # Goulburn Mulwaree moved to Resolve for its 18 February 2025 meeting; the
    # tenant holds nothing earlier. Meetings from 2018 to 28 January 2025 are
    # on the council's OpenCities listing
    # (https://www.goulburn.nsw.gov.au/Council/Agendas-and-Minutes), which
    # this scraper does not read yet: its papers are labelled "Business
    # Paper", which the OpenCities base class does not take for an agenda.
    tenant = "goulburn"

    # Council meetings only. The tenant's other type is the Public Forum held
    # the week before each Council meeting, where residents address
    # councillors and nothing is decided; dropping it halves the detail calls.
    meeting_types = re.compile(r"^(Ordinary|Extra Ordinary) Council Meeting$")

    # The council spells it as two words, which the base class's special-
    # meeting check does not recognise.
    meeting_type_names = {
        "Extra Ordinary Council Meeting": "Extraordinary Council Meeting"
    }

    def __init__(self):
        super().__init__("goulburn_mulwaree", "NSW")
