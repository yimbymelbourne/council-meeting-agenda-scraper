import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class MitchamScraper(ResolveScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 17 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 17

    # Mitcham's minutes-and-agendas page frames its Resolve portal and holds
    # no listing of its own. Its LGA SA Funnelback collection exists but is
    # empty, so Resolve is the only source.
    tenant = "mitcham"

    # Full Council (special meetings included) and the planning bodies: the
    # Council Assessment Panel, its predecessor the Development Assessment
    # Panel, and the Strategic Planning and Development Policy Committee.
    # Left out are audit, CEO review, grants, information sessions and the
    # advisory groups; each kept meeting costs a request to learn which
    # documents it has.
    meeting_types = re.compile(
        r"^(Full Council|Council Assessment Panel|Development Assessment Panel"
        r"|Strategic Planning and Development Policy Committe)"
    )
    # The tenant stores type names cut off at 50 characters.
    meeting_type_names = {
        "Strategic Planning and Development Policy Committe": (
            "Strategic Planning and Development Policy Committee"
        )
    }

    # The 20 January 2022 panel is entered twice; event 961 repeats event
    # 1006, down to byte-identical minutes.
    skip_events = frozenset({961})

    # Named "3 March 2022 Council Assessment Panel" and its minutes say so,
    # but it is dated 3 August 2023. No other event holds 3 March 2022.
    event_dates = {959: "2022-03-03"}

    # Where the packet is the wrong document. Measured by downloading both
    # for every Mitcham meeting that has both (2026-10-19); these are the
    # only ones where the bare agenda is the bigger.
    agenda_documents = {
        # In early 2022 Full Council the packet is a one-page "Please refer
        # to the agenda document for this meeting" (110 KB); the agenda is
        # the real one, 9 to 42 MB.
        278: "agenda",
        279: "agenda",
        280: "agenda",
        # Panel meetings whose packet holds only part of the papers: 1.6 MB,
        # 10 MB and 9 MB against agendas of 72 MB, 107 MB and 72 MB.
        998: "agenda",
        1004: "agenda",
        1006: "agenda",
        # 5 May 2022 panel: agenda and packet are the same one-page cover
        # sheet, and the agenda it points to was never attached. Minutes
        # only.
        954: None,
    }

    def __init__(self):
        super().__init__("mitcham", "SA")
