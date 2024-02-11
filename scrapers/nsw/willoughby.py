import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from base_scraper import BaseScraper, register_scraper
from logging.config import dictConfig
from _dataclasses import ScraperReturn
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Union


@register_scraper
class WilloughbyNSWScraper(BaseScraper):
    def __init__(self):
        council = "willoughby"
        state = "NSW"
        base_url = "https://www.willoughby.nsw.gov.au"
        super().__init__(council, state, base_url)

    def council_minutes_scraper(self, meeting_url) -> Union[ScraperReturn, None]:
        output = self.fetch_with_requests(meeting_url)
        soup = BeautifulSoup(output.content, "html.parser")
        div = soup.find('div', class_='meeting-container')  # Find the main container
        meeting_info = {
            'name': None,
            'date': None,
            'time': None,
            'webpage_url' : meeting_url,
            'download_url' : None,
        }

        meeting_date = soup.find('h1', class_='oc-page-title').text
        meeting_info['date'] = meeting_date
        # Normalise dates
        date_obj = datetime.strptime(meeting_date, '%d %B %Y')
        current_date = datetime.now()
        # if it's in the past BYE BYE
        if date_obj < current_date:
            return None
        # Meeting title
        meeting_type_p = div.find('p')
        meeting_info['name'] = meeting_type_p.text if meeting_type_p else None

        # Time
        meeting_time_div = div.find('div', class_='meeting-time')
        if meeting_time_div:
            meeting_time_text = meeting_time_div.text.split("Time")
            if len(meeting_time_text) > 1:
                time_str = meeting_time_text[1].strip() 
                time_obj = datetime.strptime(time_str, '%I:%M %p')
                # all my homies only like 24 hour time
                meeting_info['time'] = time_obj.strftime('%H:%M')

        # Extract agenda link
        agenda_link_tag = div.find('a', class_='document', href=True)
        if agenda_link_tag:
            link = agenda_link_tag['href']
            meeting_info['download_url'] = "https://www.willoughby.nsw.gov.au" + link

        # Check if any of the values are None and return the object or None accordingly
        if None in meeting_info.values():
            meeting_info = None

        return meeting_info


    def scraper(self): # -> ScraperReturn | None:
        self.logger.info(f"Starting {self.council_name} scraper")
        webpage_url = "https://www.willoughby.nsw.gov.au/Council/Council-meetings/General-Council-Meetings"

        name = None
        date = None
        time = None
        download_url = None

        output = self.fetch_with_requests(webpage_url)

        soup = BeautifulSoup(output.content, "html.parser")

        # meetings are articles yay semantic web
        articles = soup.find_all('article')
        for article in articles:
            link = article.find('a', class_='accordion-trigger minutes-trigger ajax-trigger')
        
            # Check if the link exists
            if link:
                href = link.get('href')  
                # you can never have enough functions
                result = self.council_minutes_scraper(href)
                if result:
                    return result


        return None

if __name__ == "__main__":
    scraper = WilloughbyNSWScraper()
    scraper.scraper()

