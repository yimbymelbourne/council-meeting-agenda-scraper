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
    DEFAULTHEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.google.com/',
        'Connection': 'keep-alive',
        'accept': 'application/json'
    }    
      
    def __init__(self, council_name, state, base_url):
        self.council_name = council_name
        self.state = state
        self.base_url = base_url        
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"{self.__class__.__name__} initialized")        
        self.session = requests.Session()
        self.set_headers(self.DEFAULTHEADERS)
        self.driver = None

    def log(self, level, message, *args):
        # Prepare a message that includes council name and state
        full_message = f"[{self.council_name} - {self.state}] {message}"
        # Get the logger with the name of the current class
        logger = logging.getLogger(self.__class__.__name__)
        # Log the message with the provided level
        logger.log(level, full_message, *args)

    def set_headers(self, headers):
        # Directly replace the session's headers dictionary
        self.session.headers.clear()
        self.session.headers.update(headers)

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
