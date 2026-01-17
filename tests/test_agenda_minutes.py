#!/usr/bin/env python3
"""
Quick test to verify the agenda and minutes support works correctly.
"""
from aus_council_scrapers.base import ScraperReturn


def test_scraper_return_with_both():
    """Test ScraperReturn with both agenda and minutes."""
    result = ScraperReturn(
        name="Council Meeting",
        date="15 January 2026",
        time="18:30",
        webpage_url="https://example.com/meetings",
        agenda_url="https://example.com/agenda.pdf",
        minutes_url="https://example.com/minutes.pdf",
        download_url="https://example.com/agenda.pdf",
    )

    assert result.name == "Council Meeting"
    assert result.agenda_url == "https://example.com/agenda.pdf"
    assert result.minutes_url == "https://example.com/minutes.pdf"
    assert result.download_url == "https://example.com/agenda.pdf"
    print("✓ Test passed: ScraperReturn with both agenda and minutes")


def test_scraper_return_agenda_only():
    """Test ScraperReturn with only agenda."""
    result = ScraperReturn(
        name="Council Meeting",
        date="15 January 2026",
        time="18:30",
        webpage_url="https://example.com/meetings",
        agenda_url="https://example.com/agenda.pdf",
        minutes_url=None,
        download_url="https://example.com/agenda.pdf",
    )

    assert result.agenda_url == "https://example.com/agenda.pdf"
    assert result.minutes_url is None
    print("✓ Test passed: ScraperReturn with agenda only")


def test_scraper_return_backward_compatible():
    """Test ScraperReturn with legacy download_url only."""
    result = ScraperReturn(
        name="Council Meeting",
        date="15 January 2026",
        time="18:30",
        webpage_url="https://example.com/meetings",
        download_url="https://example.com/agenda.pdf",
    )

    assert result.download_url == "https://example.com/agenda.pdf"
    assert result.agenda_url is None
    assert result.minutes_url is None
    print("✓ Test passed: ScraperReturn with backward compatible download_url")


def test_validation_requires_at_least_one_url():
    """Test that validation requires at least one URL."""
    result = ScraperReturn(
        name="Council Meeting",
        date="15 January 2026",
        time="18:30",
        webpage_url="https://example.com/meetings",
        agenda_url="https://example.com/agenda.pdf",
    )

    try:
        result.check_required_properties("NSW")
        print("✓ Test passed: Validation with agenda_url")
    except ValueError as e:
        print(f"✗ Test failed: {e}")
        raise


def test_validation_fails_without_urls():
    """Test that validation fails when no URLs provided."""
    result = ScraperReturn(
        name="Council Meeting",
        date="15 January 2026",
        time="18:30",
        webpage_url="https://example.com/meetings",
    )

    try:
        result.check_required_properties("NSW")
        print("✗ Test failed: Should have raised ValueError")
        raise AssertionError("Expected ValueError")
    except ValueError as e:
        if "No document URLs found" in str(e):
            print("✓ Test passed: Validation correctly fails without URLs")
        else:
            raise


def test_to_dict_includes_all_urls():
    """Test that to_dict includes all URL fields."""
    result = ScraperReturn(
        name="Council Meeting",
        date="15 January 2026",
        time="18:30",
        webpage_url="https://example.com/meetings",
        agenda_url="https://example.com/agenda.pdf",
        minutes_url="https://example.com/minutes.pdf",
        download_url="https://example.com/agenda.pdf",
    )

    data = result.to_dict()
    assert "agenda_url" in data
    assert "minutes_url" in data
    assert "download_url" in data
    assert data["agenda_url"] == "https://example.com/agenda.pdf"
    assert data["minutes_url"] == "https://example.com/minutes.pdf"
    print("✓ Test passed: to_dict includes all URL fields")


if __name__ == "__main__":
    print("Running tests for agenda and minutes support...\n")

    test_scraper_return_with_both()
    test_scraper_return_agenda_only()
    test_scraper_return_backward_compatible()
    test_validation_requires_at_least_one_url()
    test_validation_fails_without_urls()
    test_to_dict_includes_all_urls()

    print("\n✓ All tests passed!")
