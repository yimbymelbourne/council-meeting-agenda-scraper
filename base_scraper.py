# base_scraper.py
import logging
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

scraper_registry = {}

def register_scraper(cls):
    scraper_registry[cls.__name__] = cls()
    return cls

class BaseScraper:
    def __init__(self, council_name, state, base_url):
        self.council_name = council_name
        self.state = state
        self.base_url = base_url        
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"{self.__class__.__name__} initialized")        
        self.session = requests.Session()
        self.driver = None

    def setup_selenium_driver(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        self.driver = webdriver.Chrome(options=chrome_options)

    def fetch_with_requests(self, url, method='GET', **kwargs):
        if method.upper() == 'POST':
            response = self.session.post(url, **kwargs)
        else:
            response = self.session.get(url, **kwargs)
        return response

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        if not self.driver:
            self.setup_selenium_driver()
        self.driver.get(url)
        if wait_condition:
            WebDriverWait(self.driver, wait_time).until(wait_condition)
        return self.driver.page_source

    def scraper(self):
        raise NotImplementedError("Scrape method must be implemented by the subclass.")

    def close(self):
        if self.driver:
            self.driver.quit()
