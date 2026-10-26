from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.datascape import DatascapeMeetingsScraper

# Shire of Manjimup. One item per meeting under the "Council Meeting"
# category, which covers both ordinary and special meetings; the committees,
# agenda briefings and electors' meetings have categories of their own and
# are not read. Each item links the agenda, the attachments (left out), a
# combined agenda-and-attachments file of up to 240 MB (used only when the
# plain agenda is missing) and the minutes.
#
# manjimup.infocouncil.biz still answers but stopped in June 2024; this
# listing goes back to 2013 and is the one the council links.
#
# Served direct (x-powered-by: ASP.NET), no CDN or WAF headers seen from a
# home IP. robots.txt: Allow / with Crawl-delay: 7.


@register_scraper
class ManjimupScraper(DatascapeMeetingsScraper):
    # Refused from GitHub-hosted runners (403, 405 or a connection timeout,
    # measured 20 Oct 2026 by running every state shard from a runner) and
    # reachable from a home connection, so it goes through the residential
    # egress. See AGENTS.md, "Councils that block GitHub's runners".
    egress = "residential"

    listing_url = "https://www.manjimup.wa.gov.au/our-council/meetings"
    category = "council-meeting"
    # Its own share is about 71-78 s (11 requests at the 7 s crawl delay)
    # for a production year, but it takes turns with the other councils on
    # Datascape's shared server, and the three together took 270-274 s
    # (20 Oct 2026). Set to the group's time so all three start first.
    expected_seconds = 275.0

    def __init__(self):
        super().__init__("manjimup", "WA", "https://www.manjimup.wa.gov.au")
