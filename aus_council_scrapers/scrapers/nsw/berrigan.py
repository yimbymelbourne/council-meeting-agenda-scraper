import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class BerriganScraper(ResolveScraper):
    # Berrigan's Resolve record starts with its 18 September 2024 Ordinary
    # meeting. Its business papers from 2014 to February 2026 are also on an
    # OpenCities listing ("Business Papers 2025 and previous years") whose
    # rows link to a page per meeting. That archive is not read here, so
    # history starts at the move, and three gaps in the tenant stay open:
    # the 7 July 2025 special meeting is not on Resolve at all, the 30
    # October 2025 one is there unpublished, and four 2025 Ordinary meetings
    # (19 February, 16 April, 21 May, 20 August) have their agendas on
    # Resolve but their minutes only in the archive. The archive's last
    # meetings, January and February 2026, are on Resolve in full, so the
    # current year is complete without it.
    tenant = "berriganshire"

    # Ordinary and Extraordinary Council meetings. Left out is the Public
    # Forum, held just before some Council meetings for residents to address
    # councillors, where nothing is decided. Each kept meeting costs a
    # request to learn which documents it has.
    meeting_types = re.compile(r"^(Ordinary Council|Extraordinary Council Meeting)$")

    # The two types are named differently for the same body.
    meeting_type_names = {"Ordinary Council": "Ordinary Council Meeting"}

    # Until February 2026 Berrigan uploaded its own PDFs rather than building
    # agendas in Resolve, so the "packet" slot holds whatever file the council
    # put there. Page 1 of every such packet reads "Agenda" for its meeting
    # except one: the 21 January 2026 packet is the "Under Separate Cover
    # Appendices" file (162 pages), and the bare agenda is the full business
    # paper (92 pages).
    agenda_documents = {45: "agenda"}

    def __init__(self):
        super().__init__("berrigan", "NSW")
