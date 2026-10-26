"""District Council of Ceduna.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The committee
label is right nearly always, but EPRAP's 14 September 2026 minutes were
filed under "Council", which made a council meeting of them, so the panel is
recognised by its title too. Confidential minutes released later are filed
under the day of release, and are dropped when that is not a meeting day
(see `_FROM_CONFIDENCE`).
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper


@register_scraper
class CedunaScraper(LGASAFunnelbackScraper):
    listing_urls = ("https://www.ceduna.sa.gov.au/council/minutes-and-agendas",)

    # The Eyre Peninsula Regional Assessment Panel decides development
    # applications for Ceduna and the other Eyre Peninsula member councils;
    # it is kept, as the body that assesses this council's applications.
    body_from_title = (
        (
            r"\bEPRAP\b|Eyre Peninsula Regional Assessment Panel",
            "Eyre Peninsula Regional Assessment Panel",
        ),
    )

    # The Audit Committee became the Audit and Risk Committee in the 2021
    # local government reforms, and the council files its papers under both
    # labels—31 May 2021's agenda under one and its minutes under the
    # other—so both are one body.
    committee_names = {
        "Audit Committee": "Audit and Risk Committee",
        "Audit & Risk Committee": "Audit and Risk Committee",
    }

    # The Australia Day Awards Judging Panel meets once a year to choose
    # award recipients from community nominations; its papers are those
    # nominations, not council business.
    skip_committees = frozenset({"Australia Day Judging Panel"})

    # A paper filed alone under a day its title and file name both
    # contradict was filed under its publication day; see `_restated_date`.
    restate_lone_dates = True

    def __init__(self):
        super().__init__("ceduna", "SA", "https://www.ceduna.sa.gov.au")
