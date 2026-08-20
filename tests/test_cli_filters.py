"""The `--council` / `--state` selectors, which another repo depends on.

Live scraping is driven by `council-alerts`, whose adapter builds
`--council a,b` from its workflow input. A single-name comparison matched
nothing against that, so a multi-council run scraped no councils and returned
a successful, empty result — the worst shape of failure, because it looks like
the councils published nothing.
"""

from aus_council_scrapers.main import _matches


def test_single_name():
    assert _matches("melbourne", "melbourne")
    assert not _matches("melbourne", "merri_bek")


def test_comma_separated_list_as_council_alerts_sends_it():
    assert _matches("merri_bek,yarra", "yarra")
    assert _matches("merri_bek,yarra", "merri_bek")
    assert not _matches("merri_bek,yarra", "melbourne")


def test_tolerates_spacing_and_case():
    assert _matches("Merri_Bek, YARRA", "yarra")
    assert _matches("VIC, NSW", "vic")


def test_empty_entries_do_not_match_everything():
    """A trailing comma or a stray space must not turn into a wildcard."""
    assert not _matches("melbourne,", "yarra")
    assert not _matches(",", "yarra")
