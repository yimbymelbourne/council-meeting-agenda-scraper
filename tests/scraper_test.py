import pytest
import os.path
import json

from council_scrapers.base import (
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
        return self.__processed_replay_data[("requests", url, method)]

    def fetch_with_selenium(self, url):
        return self.__processed_replay_data[("selenium", url)]


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
    if scraper_instance.council_name in ["bayside_vic", "melbourne"]:
        pytest.skip("Seems broken before..")
    if os.path.exists(test_result) and os.path.exists(test_replay_data):
        with open(test_result, "r") as f:
            expected_result = ScraperReturn.from_dict(json.load(f))
        with open(test_replay_data, "r") as f:
            json_replay_data = json.load(f)

        fetcher = PlaybackFetcher(json_replay_data)
        scraper_instance.fetcher = fetcher
        result = scraper_instance.scraper()
        assert result == expected_result
    else:
        recorder = RecordingFetcher(DefaultFetcher())
        scraper_instance.fetcher = recorder
        result = scraper_instance.scraper()

        json_result = json.dumps(result.to_dict())
        with open(test_replay_data, "w") as f:
            f.write(json.dumps(recorder.replay_data))
        with open(test_result, "w") as f:
            f.write(json_result)
        recorder.close()
