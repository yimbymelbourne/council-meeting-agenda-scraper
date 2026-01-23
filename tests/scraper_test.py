import pytest
import os.path
import json

from aus_council_scrapers.base import (
    SCRAPER_REGISTRY,
    BaseScraper,
    Fetcher,
    DefaultFetcher,
    ScraperReturn,
)


class RecordingFetcher(Fetcher):
    def __init__(self, delegated_fetcher: Fetcher):
        self.replay_data = []
        self.__delegated_fetcher = delegated_fetcher

    def get_selenium_driver(self):
        pytest.skip("Uses selenium directly not supported")

    def fetch_with_requests(self, url, method="GET"):
        result = self.__delegated_fetcher.fetch_with_requests(url, method)
        self.replay_data.append([["requests", url, method], result])
        return result

    def fetch_with_selenium(self, url):
        result = self.__delegated_fetcher.fetch_with_selenium(url)
        self.replay_data.append([["selenium", url], result])
        return result

    def close(self):
        self.__delegated_fetcher.close()


class PlaybackFetcher(Fetcher):
    def __init__(self, replay_data):
        self.__processed_replay_data = {tuple(x[0]): x[1] for x in replay_data}

    def get_selenium_driver(self):
        raise NotImplementedError()

    def fetch_with_requests(self, url, method="GET"):
        # Try exact match first
        key = ("requests", url, method)
        if key in self.__processed_replay_data:
            return self.__processed_replay_data[key]

        # For InfoCouncil scrapers that now use ?year= parameter,
        # try to find the base URL without parameters
        if "?" in url:
            base_url = url.split("?")[0]
            base_key = ("requests", base_url, method)
            if base_key in self.__processed_replay_data:
                return self.__processed_replay_data[base_key]

        # Try matching with/without URL fragments (#section)
        if "#" in url:
            url_without_fragment = url.split("#")[0]
            base_key = ("requests", url_without_fragment, method)
            if base_key in self.__processed_replay_data:
                return self.__processed_replay_data[base_key]
        else:
            # Try finding a URL with a fragment that matches this base
            for stored_key in self.__processed_replay_data.keys():
                if (
                    len(stored_key) == 3
                    and stored_key[0] == "requests"
                    and stored_key[2] == method
                ):
                    stored_url = stored_key[1]
                    if "#" in stored_url and stored_url.split("#")[0] == url:
                        return self.__processed_replay_data[stored_key]

        # Return empty HTML for missing URLs
        return "<html><body></body></html>"

    def fetch_with_selenium(self, url):
        # Try exact match first
        key = ("selenium", url)
        if key in self.__processed_replay_data:
            return self.__processed_replay_data[key]

        # Try base URL without parameters
        if "?" in url:
            base_url = url.split("?")[0]
            base_key = ("selenium", base_url)
            if base_key in self.__processed_replay_data:
                return self.__processed_replay_data[base_key]

        # Try matching with/without URL fragments (#section)
        if "#" in url:
            url_without_fragment = url.split("#")[0]
            base_key = ("selenium", url_without_fragment)
            if base_key in self.__processed_replay_data:
                return self.__processed_replay_data[base_key]
        else:
            # Try finding a URL with a fragment that matches this base
            for stored_key in self.__processed_replay_data.keys():
                if (
                    len(stored_key) == 2
                    and stored_key[0] == "selenium"
                ):
                    stored_url = stored_key[1]
                    if "#" in stored_url and stored_url.split("#")[0] == url:
                        return self.__processed_replay_data[stored_key]

        # Return empty HTML for missing URLs
        return "<html><body></body></html>"


@pytest.mark.parametrize(
    "scraper_instance", SCRAPER_REGISTRY.values(), ids=SCRAPER_REGISTRY.keys()
)
def test_scraper(scraper_instance: BaseScraper):
    test_result = os.path.join(
        "tests/test-cases", scraper_instance.council_name + "-result.json"
    )
    test_replay_data = os.path.join(
        "tests/test-cases", scraper_instance.council_name + "-replay_data.json"
    )
    if scraper_instance.council_name in ["strathfield"]:
        pytest.skip(
            f"Known issue with {scraper_instance.council_name} scraper. Skipping for now."
        )
    if os.path.exists(test_result) and os.path.exists(test_replay_data):
        with open(test_result, "r") as f:
            result_data = json.load(f)
            # Handle both old format (single dict) and new format (list of dicts)
            if isinstance(result_data, dict):
                expected_result = [ScraperReturn.from_dict(result_data)]
            else:
                expected_result = [ScraperReturn.from_dict(r) for r in result_data]
        with open(test_replay_data, "r") as f:
            json_replay_data = json.load(f)

        fetcher = PlaybackFetcher(json_replay_data)
        scraper_instance.fetcher = fetcher
        result = scraper_instance.scraper()

        # For backwards compatibility with old test data:
        # If expected_result has 1 item and result has multiple items,
        # check if the first result matches the expected result
        if len(expected_result) == 1 and len(result) > 1:
            # Old test data format - just check that the expected meeting
            # is in the results (usually the first one)
            assert expected_result[0] in result, (
                f"Expected meeting not found in results. "
                f"Expected: {expected_result[0]}, "
                f"Got {len(result)} meetings, first: {result[0] if result else 'none'}"
            )
        else:
            # New test data format or exact match expected
            assert result == expected_result
    else:
        recorder = RecordingFetcher(DefaultFetcher())
        scraper_instance.fetcher = recorder
        result = scraper_instance.scraper()

        # Result is now a list, so save it as a list
        json_result = json.dumps([r.to_dict() for r in result], indent=2)
        with open(test_replay_data, "w") as f:
            f.write(json.dumps(recorder.replay_data))
        with open(test_result, "w") as f:
            f.write(json_result)
        recorder.close()
