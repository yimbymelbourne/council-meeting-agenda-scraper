"""The production fetch bound for the nine CouncilConnect councils of A-CC-2.

Replay proves the full history parses; it says nothing about one production
night, which asks for a single year. These councils pay a request per
meeting, so the CouncilConnect cost checks in test_councilconnect.py are run
against their cassettes too: one year fetches only that year's listings,
stays within the request budget, and still finds every meeting of that year;
and no emitted document URL carries the file store's moving version.
"""

import pytest

import tests.test_councilconnect as councilconnect_tests
from tests.test_councilconnect import (
    test_document_urls_carry_no_file_store_version as _no_versioned_urls,
    test_one_year_fetches_only_that_year_and_loses_nothing as _one_year,
)

A_CC_2_SCRAPERS = [
    "MacDonnellScraper",
    "DenmarkScraper",
    "DonnybrookBalingupScraper",
    "BridgetownGreenbushesScraper",
    "PlantagenetScraper",
    "CarnarvonScraper",
    "ToodyayScraper",
    "WaroonaScraper",
    "KatanningScraper",
]

# Toodyay is already read for its Council meetings alone, and still held 17
# of them with papers by October 2026: the two year listings, 17 meeting
# pages, the upcoming page and one upcoming meeting with no papers yet make
# 21 requests (43 s), one over the default.
REQUEST_BUDGET_OVERRIDES = {"ToodyayScraper": 22}


@pytest.mark.parametrize("class_name", A_CC_2_SCRAPERS)
def test_one_year_fetches_only_that_year_and_loses_nothing(class_name, monkeypatch):
    for name, budget in REQUEST_BUDGET_OVERRIDES.items():
        monkeypatch.setitem(councilconnect_tests.REQUEST_BUDGET_OVERRIDES, name, budget)
    _one_year(class_name)


@pytest.mark.parametrize("class_name", A_CC_2_SCRAPERS)
def test_document_urls_carry_no_file_store_version(class_name):
    _no_versioned_urls(class_name)
