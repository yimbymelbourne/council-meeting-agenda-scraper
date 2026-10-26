"""District Council of Franklin Harbour.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. Two habits of
this council shaped the base class. It publishes every council meeting's
minutes as "<Month> <Year> Minutes & Attachments", which the base class used
to drop as an attachment. And its titles give only the month ("October 2026
Notice of Meeting & Agenda"), so a meeting whose agenda and minutes were
filed under different days is joined on the month the titles name, and
dated from the agenda's file name ("120826-Notice-of-Meeting-and-Agenda.pdf")
when that falls between them; see `_rejoin_misdated`.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper


@register_scraper
class FranklinHarbourScraper(LGASAFunnelbackScraper):
    # The whole collection: Council, the Audit Committee and two advisory
    # committees that last met in 2017.
    listing_urls = (
        "https://www.franklinharbour.sa.gov.au/your-council/agendas-and-minutes",
    )

    # "Lucky Bay" holds the minutes of the Lucky Bay Shackowners Association
    # ("Lucky-Bay-Shackowners-Assoc-22-Sept-2020.pdf"), a residents'
    # association whose papers the council republishes; its meetings are not
    # the council's. "Cowell Cottages" holds two sets of 2016 minutes, before
    # anything this scraper asks for.
    skip_committees = frozenset({"Lucky Bay", "Cowell Cottages"})

    # A paper filed alone under a day its title and file name both
    # contradict was filed under its publication day; see `_restated_date`.
    restate_lone_dates = True

    def __init__(self):
        super().__init__(
            "franklin_harbour", "SA", "https://www.franklinharbour.sa.gov.au"
        )
