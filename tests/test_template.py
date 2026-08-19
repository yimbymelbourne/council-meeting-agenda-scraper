"""Keep `docs/scraper_template.py` matching the API it claims to demonstrate.

The template is the first thing anyone copies when adding a council, so a
stale one starts every new scraper wrong. It previously returned a single
`ScraperReturn | None` long after scrapers moved to returning lists, and
demonstrated the deprecated positional `download_url` call — nothing caught
either, because nothing imported it.
"""

import ast
import importlib.util
import typing

import pytest

from aus_council_scrapers.base import SCRAPER_REGISTRY, BaseScraper, ScraperReturn

TEMPLATE_PATH = "docs/scraper_template.py"


@pytest.fixture
def template_class():
    """Import the template without leaving it in the scraper registry.

    Importing runs @register_scraper, which would otherwise add a fake
    council to every parametrised scraper test and send it to the network.
    """
    before = dict(SCRAPER_REGISTRY)
    spec = importlib.util.spec_from_file_location("_scraper_template", TEMPLATE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    added = [k for k in SCRAPER_REGISTRY if k not in before]
    try:
        yield module.CouncilScraper
    finally:
        for key in added:
            del SCRAPER_REGISTRY[key]


def test_template_imports_and_subclasses_base(template_class):
    assert issubclass(template_class, BaseScraper)


def test_template_registers_itself(template_class):
    """Forgetting @register_scraper is a real failure mode, so the template
    must model it."""
    assert "@register_scraper" in open(TEMPLATE_PATH).read()


def test_template_returns_a_list_of_meetings(template_class):
    """The signature scrapers actually have — not the single-object one the
    template advertised for months after the API changed."""
    hints = typing.get_type_hints(template_class.scraper)
    assert hints.get("return") == list[ScraperReturn]


def test_template_does_not_use_the_real_clock():
    """A scraper reading datetime.now() expires its own cassette every
    January; the template must not teach that.

    Checked against the parsed syntax tree, so the comment explaining the
    rule does not count as a violation of it.
    """
    tree = ast.parse(open(TEMPLATE_PATH).read())
    calls = {
        ast.unparse(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "clock.current_year" in calls
    assert not {"datetime.now", "datetime.datetime.now", "date.today"} & calls


def test_template_keeps_agenda_and_minutes_on_one_record():
    """Emitting an agenda row and a separate minutes row for one meeting is a
    known failure mode; the template must build a single record carrying
    both."""
    tree = ast.parse(open(TEMPLATE_PATH).read())
    constructions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "ScraperReturn"
    ]
    assert constructions, "template never constructs a ScraperReturn"
    keywords = {kw.arg for kw in constructions[0].keywords}
    assert {"agenda_url", "minutes_url"} <= keywords
    # Every field should be passed by name — the positional form is what the
    # old template demonstrated, and it silently binds to download_url.
    assert not constructions[0].args


def test_template_can_be_instantiated(template_class):
    """Catches drift in BaseScraper.__init__ that would break every copy."""
    scraper = template_class()
    assert scraper.council_name
    assert scraper.state
    assert scraper.base_url.startswith("http")
