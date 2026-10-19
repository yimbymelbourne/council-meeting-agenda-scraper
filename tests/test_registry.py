"""The registry has to hold every scraper exactly once.

`register_scraper` keys the registry by class name, so a second class with the
same name silently replaces the first: the first council stops running in
production and its fixture just stops replaying, and nothing fails. And a
decorated class whose module is never imported is never registered at all.
These tests read the decorators out of the source, so they see both.
"""

import ast
import glob
import os
from collections import Counter

import aus_council_scrapers.scrapers  # noqa: F401  (fills the registry)
from aus_council_scrapers.base import SCRAPER_REGISTRY

# Decorated, but no `__init__.py` imports them, so they have never run. Each
# one leaves this list in the change that imports it. The test below fails on
# a stale entry, so the list cannot outlive its fix.
KNOWN_UNIMPORTED = {
    "MooneeValleyScraper",
}


def _decorated_classes() -> list[tuple[str, str]]:
    """(class name, file) for every class decorated with `register_scraper`."""
    found = []
    for path in sorted(glob.glob("aus_council_scrapers/**/*.py", recursive=True)):
        tree = ast.parse(open(path).read(), path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name) and decorator.id == "register_scraper":
                    found.append((node.name, path))
    return found


def _fixture_slugs() -> set[str]:
    return {
        os.path.basename(p).replace("-result.json", "")
        for p in glob.glob("tests/test-cases/*-result.json")
    }


def test_no_two_scraper_classes_share_a_name():
    decorated = _decorated_classes()
    assert decorated, "found no @register_scraper classes"
    counts = Counter(name for name, _ in decorated)
    clashes = {
        name: [path for n, path in decorated if n == name]
        for name, count in counts.items()
        if count > 1
    }
    assert not clashes, (
        f"these scraper classes share a name, so only one of each is registered: "
        f"{clashes}"
    )


def test_every_decorated_scraper_is_registered():
    decorated = {name for name, _ in _decorated_classes()}
    unregistered = decorated - set(SCRAPER_REGISTRY)
    assert unregistered - KNOWN_UNIMPORTED == set(), (
        f"decorated but never imported, so they never run: "
        f"{sorted(unregistered - KNOWN_UNIMPORTED)}. Import them in the "
        f"state's __init__.py."
    )
    stale = KNOWN_UNIMPORTED - unregistered
    assert not stale, f"now registered; drop them from KNOWN_UNIMPORTED: {sorted(stale)}"


def test_no_two_scrapers_share_a_slug():
    counts = Counter(s.council_name for s in SCRAPER_REGISTRY.values())
    assert not [slug for slug, n in counts.items() if n > 1]


def test_every_registered_scraper_has_a_fixture_and_every_fixture_a_scraper():
    registered = {s.council_name for s in SCRAPER_REGISTRY.values()}
    fixtures = _fixture_slugs()
    assert not registered - fixtures, (
        f"registered with no fixture: {sorted(registered - fixtures)}"
    )
    assert not fixtures - registered, (
        f"a fixture no registered scraper replays: {sorted(fixtures - registered)}"
    )
