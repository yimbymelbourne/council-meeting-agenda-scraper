import urllib.parse

import requests
from bs4 import BeautifulSoup

from _dataclasses import Council, ScraperReturn


def scraper() -> ScraperReturn | None:
    url = "https://infoweb.bayside.nsw.gov.au/?committee=1"

    agendas = requests.get(url)
    soup = BeautifulSoup(agendas.content, "html.parser")

    meeting_table = soup.find("table", id="grdMenu", recursive=True)
    if meeting_table is None:
        # There were no meetings for this year.
        # Try with previous year (append "&year=2023") if you want to confirm this is working
        return None
    current_meeting = meeting_table.find("tbody").find_all("tr")[0]

    relative_pdf_url = current_meeting.find("a", class_="bpsGridPDFLink", recursive=True).attrs["href"]
    return ScraperReturn(
        name=current_meeting.find("td", class_="bpsGridCommittee").text,
        date=current_meeting.find("td", class_="bpsGridDate").text,
        time="",
        webpage_url=url,
        download_url=urllib.parse.urljoin(url, relative_pdf_url))


bayside_nsw = Council(
    name="bayside_nsw",
    scraper=scraper,
)
