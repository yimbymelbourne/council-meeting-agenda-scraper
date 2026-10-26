"""Recognise the meeting-publishing platform a council runs.

Councils rarely build their own agenda system — they buy one of a handful,
and several of those already have a base class here. Identifying the platform
before writing a parser is the difference between a ten-line subclass and a
day of BeautifulSoup, so it is the first thing worth checking.

Signatures are matched against both the page body and its URL, because a
council's own site often just links out to the platform rather than
containing its markup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Platform:
    name: str
    #: Regexes matched case-insensitively against the URL and page body.
    signatures: tuple[str, ...]
    #: What to do about it.
    guidance: str
    #: An existing scraper to copy, if we already handle this platform.
    reference: str | None = None


PLATFORMS: tuple[Platform, ...] = (
    Platform(
        name="InfoCouncil",
        signatures=(r"infocouncil\.biz", r"bpsGridPDFLink", r"grdMenu"),
        guidance=(
            "Subclass InfoCouncilScraper and pass the infocouncil URL. "
            "Usually about ten lines — do not write a parser."
        ),
        reference="aus_council_scrapers/scrapers/nsw/innerwest.py",
    ),
    Platform(
        name="docspublished",
        signatures=(r"docspublished\.com\.au",),
        guidance="JSON API. Copy the request/parse shape from Parramatta.",
        reference="aus_council_scrapers/scrapers/nsw/parramatta.py",
    ),
    Platform(
        name="Resolve",
        signatures=(r"resolve\.red", r"Resolve Public", r"boardsync-theme"),
        guidance=(
            "Subclass ResolveScraper with the portal subdomain as `tenant`, "
            "plus a `meeting_types` pattern—every kept meeting costs one "
            "detail request to learn which documents it has."
        ),
        reference="aus_council_scrapers/resolve.py",
    ),
    Platform(
        name="OpenCities",
        signatures=(
            r"OCServiceHandler\.axd",
            r"ocsvc/Public/meetings",
            r"accordion-list-item-container",
        ),
        guidance=(
            "Subclass OpenCitiesMeetingsScraper (aus_council_scrapers/"
            "opencities.py) with the listing URL, its dlv_ list name and "
            "papers_by. Meeting detail comes from the OCServiceHandler "
            "endpoint, keyed by the cvid on each listing row; rows with no "
            "cvid, only a link to a page per meeting, use detail_pages = True. "
            "Each kept meeting costs a request, so cut a council with many "
            "committees down with meeting_types."
        ),
        reference="aus_council_scrapers/scrapers/vic/kingston.py",
    ),
    Platform(
        # After OpenCities: the generator tag is on every OpenCities site, so
        # a meetings-module page matches both and lists the module first.
        name="OpenCities content pages",
        signatures=(r'name="generator" content="OpenCities',),
        guidance=(
            "An OpenCities site. If the meetings page has no "
            "accordion-list-item-container rows and its papers are direct "
            "/files/assets/public/ links in year accordions, tables or lists, "
            "subclass OpenCitiesContentScraper "
            "(aus_council_scrapers/opencities_content.py) with its pages; one "
            "request a page, and documents are grouped into meetings by their "
            "own labels and filenames."
        ),
        reference="aus_council_scrapers/scrapers/qld/livingstone.py",
    ),
    Platform(
        name="Alyka ksearch (Kentico)",
        signatures=(r"aw_ksearch\.js", r'id="searchapi"'),
        guidance=(
            "Subclass KsearchScraper (aus_council_scrapers/alyka.py). JSON "
            "POST with the filters in SearchParam/SearchFilter headers read "
            "from the page's hidden inputs; record shape differs per council."
        ),
        reference="aus_council_scrapers/scrapers/wa/stirling.py",
    ),
    Platform(
        name="Alyka page-type listing (Kentico)",
        signatures=(r"aw_pagetypelisting\.js", r"Alyka\.MeetingDocument"),
        guidance=(
            "Subclass PageTypeListingScraper (aus_council_scrapers/alyka.py). "
            "POST {SI, PR, ...} to div#pageTypeListing[data-api]; the "
            "htmlResult fragment is parsed per council."
        ),
        reference="aus_council_scrapers/scrapers/wa/joondalup.py",
    ),
    Platform(
        name="CouncilConnect",
        signatures=(r"CouncilMeetings_usercontrol", r"lvMeetings_dpMeetings"),
        guidance=(
            "Market Creations' WA CMS. Subclass CouncilConnectScraper "
            "(aus_council_scrapers/councilconnect.py) with the site origin; "
            "set inline_documents when the year listing links the PDFs, and "
            "meeting_types when one year would cost >20 requests."
        ),
        reference="aus_council_scrapers/scrapers/wa/cottesloe.py",
    ),
    Platform(
        # After CouncilConnect: every CouncilConnect site has a document
        # library, so this only names a page that is one.
        name="CouncilConnect document library",
        signatures=(r"documentcentre-items", r"categories-dropdown"),
        guidance=(
            "CouncilConnect's /documents/ library, for councils whose papers "
            "are filed there rather than in the meetings module. Subclass "
            "CouncilConnectDocumentLibraryScraper "
            "(aus_council_scrapers/councilconnect_library.py) with the site "
            "origin; folders are found by label in the index."
        ),
        reference="aus_council_scrapers/scrapers/wa/kojonup.py",
    ),
    Platform(
        name="LGA SA Funnelback",
        signatures=(
            r"lgasa-search\.lga\.sa\.gov\.au",
            r"-council-minutes-and-agenda-push",
            r"lgasa-web\.squiz\.cloud",
        ),
        guidance=(
            "Subclass LGASAFunnelbackScraper (aus_council_scrapers/lgasa.py) "
            "and set listing_urls to the council's agendas-and-minutes page. "
            "robots.txt disallows search.json and query=/facet parameters, "
            "so it reads that page through Selenium, 20 s apart; do not "
            "write a parser."
        ),
        reference="aus_council_scrapers/scrapers/sa/port_adelaide_enfield.py",
    ),
    Platform(
        name="Craft/SimpleGov (SA)",
        signatures=(
            r"/assets/meetings/(?:\d{4}/\d{2}-[a-z]+/|agendas/|minutes/)",
            r"/assets/agendas-minutes/(?:agendas|minutes)/",
            r"table--agendasMinutes",
            r"accordion--minutes",
            r"simple\.com\.au/gov",
        ),
        guidance=(
            "Subclass CraftMeetingsModuleScraper or CraftArchiveScraper "
            "(aus_council_scrapers/craft.py) with listing_url and a row "
            "parser. The date filter needs ISO dates; AWS WAF, so Selenium "
            "unless plain requests are measured to pass."
        ),
        reference="aus_council_scrapers/scrapers/sa/salisbury.py",
    ),
    Platform(
        name="eScribe",
        # The domain, not the bare word: "escribe" matches "Subscribe".
        signatures=(r"escribemeetings\.com", r"GetCalendarMeetings"),
        guidance=(
            "Subclass EScribeScraper (aus_council_scrapers/escribe.py) and "
            "pass the portal root. One POST per year returns every meeting "
            "with its documents attached; set former_names if the council "
            "renamed its committees in place."
        ),
        reference="aus_council_scrapers/scrapers/qld/logan.py",
    ),
    Platform(
        name="Ionata meetings archive",
        signatures=(r'name="f_year"',),
        guidance=(
            "Tasmanian WordPress build with f_year/f_month/f_cat GET filters. "
            "Subclass IonataMeetingsScraper (aus_council_scrapers/ionata.py) "
            "with the listing URL and the card selectors. Kingborough's older "
            "Ionata theme has no f_year and is bespoke."
        ),
        reference="aus_council_scrapers/scrapers/tas/clarence.py",
    ),
    Platform(
        name="WP File Download",
        signatures=(r"wpfd_root_category_id", r"action=wpfd&"),
        guidance=(
            "WordPress plugin filing papers in categories, with links "
            "/download/<cat>/<slug>/<file>/<name>.pdf. Subclass "
            "WPFileDownloadScraper (aus_council_scrapers/wpfd.py) with the "
            "listing pages; categories the plugin lazy-loads over admin-ajax "
            "have no links in the page."
        ),
        reference="aus_council_scrapers/scrapers/tas/devonport.py",
    ),
    Platform(
        name="Walker Designs",
        # The agency's footer link, and the class on its meetings tables.
        signatures=(r"walkerdesigns\.com\.au", r"table-meeting"),
        guidance=(
            "Launceston agency's Craft CMS council sites. Where the meetings "
            "page is a table per year (Date | Meeting | Agenda | Minutes ...), "
            "subclass WalkerDesignsMeetingsScraper "
            "(aus_council_scrapers/walkerdesigns.py) with the listing URL; the "
            "columns are read from each table's header. The footer link alone "
            "is not the template: Dorset's site is download cards on a page "
            "per year, read by overriding listing_rows (scrapers/tas/dorset.py)."
        ),
        reference="aus_council_scrapers/scrapers/tas/meander_valley.py",
    ),
    Platform(
        name="Datascape",
        signatures=(r"cdn-sites\.datascape\.cloud",),
        guidance=(
            "ASP.NET CMS with a meetings module: ?category=&month=All&year= "
            "listing, ?item=id: item pages, files under /repository/libraries/. "
            "Subclass DatascapeMeetingsScraper (aus_council_scrapers/datascape.py) "
            "with the listing URL and the category. robots.txt sets "
            "Crawl-delay: 7, so a year costs minutes, not seconds, and the "
            "sites on lb-dds-mc2.datascape.cloud share one rate limit, so "
            "they take turns (`backend`); a Cloudflare-fronted site sets "
            "backend = None."
        ),
        reference="aus_council_scrapers/scrapers/wa/manjimup.py",
    ),
    Platform(
        name="Granicus/Legistar",
        # Granicus sells several unrelated products, including OpenCities —
        # a general council-website CMS with no connection to Legistar's
        # meeting/agenda system. Every OpenCities site credits it by URL in
        # its own generator meta tag and footer (.../product/opencities,
        # .../solution/govaccess/opencities/), which otherwise satisfies
        # this signature on any OpenCities council regardless of what
        # actually publishes its agendas — confirmed on Logan and Ipswich,
        # both really on eScribe and InfoCouncil respectively. The lookahead
        # excludes only that self-referential branding path; a genuine
        # Granicus agenda URL (a subdomain, or /solution/agenda-management/)
        # is unaffected.
        signatures=(r"granicus\.com(?![\w/-]*opencities)", r"legistar"),
        guidance="No base class yet — first council on this platform gets to write one.",
    ),
    Platform(
        name="Modern.Gov",
        signatures=(
            r"ieListMeetings\.aspx",
            r"ieListDocuments\.aspx",
            r"mgWebService\.asmx",
        ),
        guidance=(
            "Subclass ModernGovScraper (aus_council_scrapers/moderngov.py) "
            "with the base URL and a committee allowlist {CId: name}. "
            "Documents are only on per-meeting pages, so the allowlist is "
            "what bounds the cost."
        ),
        reference="aus_council_scrapers/scrapers/nsw/sydney.py",
    ),
    Platform(
        name="Civica",
        signatures=(r"civicaepathway", r"civica\.com"),
        guidance="No base class yet — first council on this platform gets to write one.",
    ),
)

#: Platform links pointing off the council's own domain.
_EXTERNAL_PLATFORM = re.compile(
    r"https?://([a-z0-9-]+\.(?:infocouncil\.biz|docspublished\.com\.au"
    r"|resolve\.red|escribemeetings\.com))",
    re.I,
)


def detect(html: str, url: str = "") -> list[Platform]:
    """Return every platform whose signature appears, most specific first."""
    haystack = f"{url}\n{html}"
    return [
        platform
        for platform in PLATFORMS
        if any(re.search(sig, haystack, re.I) for sig in platform.signatures)
    ]


def platform_links(html: str) -> set[str]:
    """Hosts the page links out to that we recognise as platforms."""
    return {match.lower() for match in _EXTERNAL_PLATFORM.findall(html)}


def is_js_challenge(headers: dict) -> bool:
    """A challenge interstitial needs a real browser.

    No User-Agent gets past one, so a council in this state wants Selenium
    rather than another header experiment. Two vendors, and the second is the
    one that bites:

    - Cloudflare answers `403` with `cf-mitigated: challenge`, which at least
      raises.
    - AWS WAF answers **`202` with an empty body** and
      `x-amzn-waf-action: challenge`. That is not an error status, so
      `fetch_with_requests` returns `""` and a scraper reports zero meetings
      while looking merely unfinished. `melbourne` sat in exactly that state.
    """
    lowered = {k.lower(): str(v).lower() for k, v in headers.items()}
    if "cf-mitigated" in lowered or "x-amzn-waf-action" in lowered:
        return True
    return "cloudflare" in lowered.get("server", "")
