"""District Council of Tumby Bay.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`, and
`TitleRulesLGASAScraper` for the title rules. The page read is the whole
collection, so the council's committees and the Eyre Peninsula Regional
Assessment Panel, which assesses development applications for Tumby Bay
and its neighbours, come with it at no extra cost.

Council papers are filed under three labels over the years ("Agenda and
Minutes", "Agenda & Minutes", "Council Meetings"), all of which the base
class already reads as the council itself.

Known misdate, left as filed: the Eyre Peninsula Regional Assessment
Panel's June 2022 meeting is emitted on 9 June 2022, the date its agenda
was filed. The meeting was on 14 June (the agenda's file name,
"AGEN2222-EPRAP-AGENDA-20220614-COMPLETE.pdf", and the minutes say so),
but the council titled the agenda "9th May 2022", so no title rule can
recover the day, and the base class rejoins the minutes, filed on the
14th, to the agenda's date.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa_titles import TitleRulesLGASAScraper


@register_scraper
class TumbyBayScraper(TitleRulesLGASAScraper):
    # The whole collection. /council/agenda-and-minutes, the "Council
    # Meetings" menu link, is a landing page.
    listing_urls = ("https://www.tumbybay.sa.gov.au/documents/agenda-and-minutes",)

    # Filed under the council's labels but never a meeting's agenda or
    # minutes:
    # - information and briefing sessions, workshops and their notices, and
    #   the "Informal Gatherings" label's papers: informal gatherings under
    #   s 90A of the Local Government Act 1999 (SA), at which no decision may
    #   be made.
    #   Filed as council papers they became "Council Meeting"s that never
    #   happened (27 January, 24 February and 24 March 2026).
    # - single reports and confidential items, released later, coded by the
    #   officer who wrote them: "LATECEO 1/823 ...", "CONFMAYOR 1/220 ...",
    #   "Minutes - CONFCEO 1/125 ...", "SPCONFGMWI 1/324 ...". "Confidential
    #   Special Council Meeting Minutes - ... - Item Released" is the
    #   confidential part only.
    # - the panels' annual reports, schedules and terms of reference.
    skip_titles = re.compile(
        r"briefing|information session|workshop|informal gathering|\blate|\b(?:sp|mes|ceo|late)?conf|"
        r"confidential|annual report|schedule of meetings|terms of reference|"
        r"prudential report|\bCEO Paper\b|amendment to report",
        re.IGNORECASE,
    )
    skip_committees = frozenset({"Informal Gatherings"})

    # Another body's papers filed under the council's label.
    refile = (
        (
            re.compile(r"CEO Performance Review", re.IGNORECASE),
            "CEO Performance Review Committee",
        ),
        # Kept apart from "Audit Committee", the same body's name until
        # 2022, so the labels the council used are the names it gets.
        (
            re.compile(r"\bAudit (?:&|and) Risk Committee", re.IGNORECASE),
            "Audit and Risk Committee",
        ),
        (re.compile(r"^Audit Committee", re.IGNORECASE), "Audit Committee"),
        (
            re.compile(r"Eyre Peninsula Regional Assessment Panel|\bEPRAP\b", re.I),
            "Eyre Peninsula Regional Assessment Panel",
        ),
    )

    def __init__(self):
        super().__init__("tumby_bay", "SA", "https://www.tumbybay.sa.gov.au")
