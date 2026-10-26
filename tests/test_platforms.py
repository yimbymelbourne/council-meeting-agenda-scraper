"""Tests for platform fingerprinting.

Pure string matching, so it is worth pinning down directly — a signature that
silently stops matching would send someone off to write a parser for a
platform already handled by a ten-line subclass.
"""

from aus_council_scrapers.platforms import (
    detect,
    is_js_challenge,
    platform_links,
)


def test_detects_infocouncil_from_the_url_alone():
    """Councils often link straight out to the platform, so the URL is a
    signature in its own right."""
    found = detect("", "https://burwood.infocouncil.biz/?year=2024")
    assert [p.name for p in found] == ["InfoCouncil"]


def test_detects_infocouncil_from_markup():
    html = '<table id="grdMenu"><a class="bpsGridPDFLink" href="x.pdf">Agenda</a></table>'
    assert [p.name for p in detect(html)] == ["InfoCouncil"]


def test_detects_opencities():
    html = '<div class="accordion-list-item-container" data-cvid="123"></div>'
    assert [p.name for p in detect(html)] == ["OpenCities"]


def test_detects_docspublished():
    found = detect("", "https://docspublished.com.au/CityofParramatta")
    assert [p.name for p in found] == ["docspublished"]


def test_detects_resolve():
    """Resolve tenants live on their own subdomain, and councils usually frame
    the portal rather than link to it, so the iframe src is what shows."""
    html = '<iframe src="https://woollahra.resolve.red/web/"></iframe>'
    assert [p.name for p in detect(html)] == ["Resolve"]
    assert platform_links(html) == {"woollahra.resolve.red"}


def test_detects_alyka_ksearch():
    """Stirling, Melville and Rockingham load the Kendo search module."""
    html = '<script src="/awcontent/web/assets/js/modules/aw_ksearch.js"></script>'
    assert [p.name for p in detect(html)] == ["Alyka ksearch (Kentico)"]


def test_detects_alyka_page_type_listing():
    """Kwinana's listing names the transformation without loading the
    script by that name, so either signature has to do."""
    script = '<script src="/awcontent/web/assets/js/modules/aw_pagetypelisting.js">'
    hidden = '<input value="Alyka.MeetingDocument.SmartSearchResults" />'
    for html in (script, hidden):
        assert [p.name for p in detect(html)] == ["Alyka page-type listing (Kentico)"]


def test_detects_councilconnect():
    html = '<div id="ctl00_CouncilMeetings_usercontrol_lvMeetings_dpMeetings">'
    assert [p.name for p in detect(html)] == ["CouncilConnect"]


def test_detects_lgasa_funnelback():
    """The listing names its push collection and links documents on the
    Matrix origin, so either is enough."""
    collection = (
        '<input name="collection" value="gawler-council-minutes-and-agenda-push">'
    )
    origin = '<a href="https://lgasa-web.squiz.cloud/?a=1873521">Agenda</a>'
    for html in (collection, origin):
        assert [p.name for p in detect(html)] == ["LGA SA Funnelback"]


def test_detects_craft_simplegov():
    """The six SA Craft sites share no one marker: the asset folders differ
    (Marion's /assets/meetings/, Playford's /assets/agendas-minutes/), and
    Holdfast Bay shows only the agency credit in its footer on page 1."""
    pages = (
        '<a href="/assets/meetings/2026/10-oct/agendas/Agenda.pdf">Agenda</a>',
        '<a href="/assets/agendas-minutes/minutes/Minutes.pdf">Minutes</a>',
        '<table class="table--agendasMinutes"></table>',
        '<p>Site by <a href="https://www.simple.com.au/gov">SimpleGov</a></p>',
    )
    for html in pages:
        assert [p.name for p in detect(html)] == ["Craft/SimpleGov (SA)"]


def test_detects_moderngov_from_the_url_alone():
    found = detect("", "https://meetings.cityofadelaide.com.au/ieListMeetings.aspx")
    assert [p.name for p in found] == ["Modern.Gov"]


def test_detects_escribe_but_not_the_word_subscribe():
    """Logan's portal is its own subdomain of the vendor, and a council page
    links out to it; the bare word "escribe" would match every "Subscribe"."""
    html = '<a href="https://pub-logancity.escribemeetings.com/">Meetings</a>'
    assert [p.name for p in detect(html)] == ["eScribe"]
    assert platform_links(html) == {"pub-logancity.escribemeetings.com"}
    assert detect("<button>Subscribe to updates</button>") == []


def test_detects_ionata_meetings_archive():
    """Clarence, Glenorchy and Sorell filter their meeting cards by year."""
    html = '<select name="f_year"><option value="2026">2026</option></select>'
    assert [p.name for p in detect(html)] == ["Ionata meetings archive"]


_OPENCITIES_GENERATOR = (
    '<meta name="generator" content="OpenCities - '
    'https://granicus.com/product/opencities" />'
)


def test_detects_opencities_content_pages_by_the_generator_tag():
    """Hepburn, Boulia and Temora never turned on the meetings module, so
    nothing but the CMS's generator tag says OpenCities. The tag names
    granicus.com, which no longer reads as Legistar (#156)."""
    html = (
        _OPENCITIES_GENERATOR + '<a href="/files/assets/public/v/1/council/documents/'
        'public-agenda-ordinary-meeting-of-council-22-september-2026.pdf">'
        "Agenda</a>"
    )
    assert [p.name for p in detect(html)] == ["OpenCities content pages"]


def test_a_meetings_module_page_names_the_module_before_content_pages():
    html = (
        _OPENCITIES_GENERATOR
        + '<div class="accordion-list-item-container" data-cvid="123"></div>'
    )
    assert [p.name for p in detect(html)][:2] == [
        "OpenCities",
        "OpenCities content pages",
    ]


def test_detects_councilconnect_document_library():
    """Kojonup and the other library councils publish papers only in
    CouncilConnect's /documents/ library, not the meetings module."""
    for html in (
        '<div class="documentcentre-items"><table class="table dc-items-table">',
        '<select id="ContentPlaceHolder1_Documents_usercontrol_ddlCategory" '
        'class="categories-dropdown form-control">',
    ):
        assert [p.name for p in detect(html)] == ["CouncilConnect document library"]


def test_detects_wp_file_download():
    """Devonport's page carries both the plugin's hidden root category and
    its admin-ajax URL."""
    for html in (
        '<input type="hidden" id="wpfd_root_category_id" value="4029" />',
        'var wpfdajaxurl = "https://www.devonport.tas.gov.au/wp-admin/'
        'admin-ajax.php?juwpfisadmin=false&action=wpfd&"',
    ):
        assert [p.name for p in detect(html)] == ["WP File Download"]


def test_detects_walker_designs():
    """Meander Valley's meetings tables, and the footer credit that is all
    Dorset's card template shares with them."""
    for html in (
        '<table class="table table-hover table-meeting"><tr><th>Date</th>',
        '<a href="http://www.walkerdesigns.com.au" rel="external">Walker Designs</a>',
    ):
        assert [p.name for p in detect(html)] == ["Walker Designs"]


def test_detects_datascape():
    html = (
        '<link href="https://cdn-sites.datascape.cloud/www.manjimup.wa.gov.au/'
        'transit-styling.css" rel="stylesheet" />'
    )
    assert [p.name for p in detect(html)] == ["Datascape"]


def test_unknown_platform_returns_nothing():
    assert detect("<html><body><h1>Meetings</h1></body></html>") == []


def test_opencities_footer_credit_does_not_also_match_granicus_legistar():
    """OpenCities is a Granicus product with no connection to Legistar's
    meeting/agenda system, but every OpenCities site credits Granicus by URL
    in its own generator meta tag and page footer. Confirmed on Logan
    (really eScribe) and Ipswich (really InfoCouncil) — both matched
    Granicus/Legistar purely from their own website's CMS credit."""
    html = (
        '<meta name="generator" content="OpenCities - '
        'https://granicus.com/product/opencities" />'
        '<span class="powered-by">Powered by '
        '<a href="https://granicus.com/solution/govaccess/opencities/">'
        "Granicus</a></span>"
    )
    # The generator tag alone now identifies an OpenCities site (content
    # pages), which is right; what must not appear is Granicus/Legistar.
    assert [p.name for p in detect(html)] == ["OpenCities content pages"]


def test_opencities_footer_credit_does_not_mask_a_real_opencities_match():
    html = (
        '<meta name="generator" content="OpenCities - '
        'https://granicus.com/product/opencities" />'
        '<div class="accordion-list-item-container"></div>'
    )
    assert [p.name for p in detect(html)] == ["OpenCities", "OpenCities content pages"]


def test_genuine_granicus_agenda_url_still_matches():
    """The exclusion is scoped to OpenCities' own branding path — an actual
    Granicus-hosted agenda subdomain is a real signal and must still match."""
    found = detect("", "https://cityname.granicus.com/ViewPublisher.php")
    assert [p.name for p in found] == ["Granicus/Legistar"]


def test_finds_platform_links_on_a_council_page():
    """A council's own page frequently just links to the platform."""
    html = '<a href="https://bayside.infocouncil.biz/Default.aspx">Business papers</a>'
    assert platform_links(html) == {"bayside.infocouncil.biz"}


def test_platform_links_ignores_unrelated_hosts():
    assert platform_links('<a href="https://www.google.com/">Search</a>') == set()


def test_recognises_a_cloudflare_challenge():
    """Distinct from a plain 403: no User-Agent gets past this one."""
    assert is_js_challenge({"cf-mitigated": "challenge", "Server": "cloudflare"})
    assert is_js_challenge({"Server": "cloudflare"})


def test_recognises_an_aws_waf_challenge():
    """The dangerous one: 202 and an empty body, so nothing raises.

    `melbourne` answered this to every header set we tried, which is why a
    scraper built on `fetch_with_requests` there found nothing and looked
    merely unfinished rather than blocked.
    """
    assert is_js_challenge({"x-amzn-waf-action": "challenge", "Server": "CloudFront"})


def test_plain_403_is_not_a_cloudflare_challenge():
    assert not is_js_challenge({"Server": "nginx"})
    assert not is_js_challenge({})


def test_every_platform_reference_exists():
    """A reference scraper that has been renamed would send someone to a file
    that is not there."""
    import os

    from aus_council_scrapers.platforms import PLATFORMS

    for platform in PLATFORMS:
        if platform.reference:
            assert os.path.exists(platform.reference), (
                f"{platform.name} points at {platform.reference}, which is missing"
            )
