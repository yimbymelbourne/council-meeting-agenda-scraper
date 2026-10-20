import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class MoreePlainsScraper(ResolveScraper):
    # Moree Plains moved to Resolve for its 16 March 2023 Ordinary meeting,
    # which is where this scraper's history starts. Its 2019-2022 papers are
    # on Joomla DOCman pages on mpsc.nsw.gov.au, where the business paper
    # and the adopted minutes are often one file and the links are /doclink/
    # URLs carrying a JWT that expires, so they are not read here.
    tenant = "moreeplains"

    # Council meetings only: "Ordinary Council Meeting" (which the council
    # also uses for most extraordinary and statutory meetings, named as such
    # in the event) and "Extraordinary Meeting". Left out is the Standing
    # Committee, which met monthly from April 2023 to February 2025 on
    # policies and quarterly reports and has listed nothing since. Each kept
    # meeting costs a request to learn which documents it has, so a body
    # that starts listing again should not be added to the nightly run
    # unasked.
    meeting_types = re.compile(r"^(Ordinary Council Meeting|Extraordinary Meeting)$")

    # The two types name the same kind of meeting differently: an
    # extraordinary meeting filed under "Ordinary Council Meeting" comes out
    # as "Extraordinary Council Meeting", so the other type is made to match.
    meeting_type_names = {"Extraordinary Meeting": "Extraordinary Council Meeting"}

    def __init__(self):
        super().__init__("moree_plains", "NSW")

    def _meeting_name(self, event: dict) -> str:
        # The first meeting after the 2024 election, where the mayor is
        # elected, is filed under "Ordinary Council Meeting" and named "2024
        # 10 15 Statutory Council Meeting".
        if _STATUTORY.search(event.get("name") or ""):
            return "Statutory Council Meeting"
        return super()._meeting_name(event)


_STATUTORY = re.compile(r"\bstatutory\b", re.IGNORECASE)
