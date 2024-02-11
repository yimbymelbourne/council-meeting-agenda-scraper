# Council Meeting Agenda Scraper

Check, download, and parse local council agendas for relevant housing and planning matters.

Users can easily set up notification functionality to be alerted by email (or: to-be-implemented, Discord) when new agendas are released.

This enables YIMBY Melbourne and other organisations to keep easy track of relevant Council activities.

## List of functioning scrapers

### Melbourne: 10/18

### Sydney: 16/30

Scraper details, including links and current status, can be found [in the docs](https://github.com/yimbymelbourne/council-meeting-agenda-scraper/blob/main/docs/councils.md) (`docs/councils.md`)

[Write a Scraper! (Instructions)](#writing-a-scraper)

# Setup

## Development

1. Setup and activate the Python environment of your choosing.

2. Ensure you have `poetry` installed (e.g. with `pip install poetry`).

3. Run `poetry shell` to ensure you've activated the correct virtual env.

4. Run `poetry install` to install dependencies.

Preferred code formatter is [Black](https://github.com/psf/black).

# Running the application

Within your environment, run: `python main.py`
Logs will print to your terminal and also get saved into /logs/ as well as writing key results to `agendas.db`.

You can run an individual scraper by running `python dir/to/scraper.py`.

## .env & Email client (optional)

In the `.env.example` file, there is the basic variable GMAIL_FUNCTIONALITY.

This functionality is turned off by default. If you want to use the email sending features here, then you'll need to include your Gmail authentication details in a `.env` file.

This may require setting up an App-specific password, for which [you can find setup instructions here](https://support.google.com/accounts/answer/185833?visit_id=638406540644584172-3254681882&p=InvalidSecondFactor&rd=1).

This functionality is optional, and the app should work fine without this setup.

# Writing a scraper

Australia has many, many councils! As such, we need many, many scrapers!

A list of most Melbourne councils, including links to their agenda webpages, can be found on the [YIMBY Melbourne website](https://www.yimbymelbourne.org.au/local-action).

Check the current issue list, or create your own. Then, build a scraper and contribute to YIMBY Melbourne's mission to create housing abundance for all Melburnians!

## How scrapers work

Scrapers for each council are contained within the `scrapers/[state]/` directory.

A scraper should be able to reliably find the most recent agenda on a Council's website. Once that link is found, it is checked against an existing database—if the link is new, then the agenda is downloaded, scanned, and a notification can be sent.

In addition to the link, the scraper function should return an object of the following shape, outlined in `_dataclasses.py`:

```py
@dataclass
class ScraperReturn:
    name: str # council name
    date: str # meeting date
    time: str # meeting time
    webpage_url: str # url of scraped page
    download_url: str # url of PDF agenda download
```

**It is not always possible to scrape the date and time of meetings from Council websites. In these cases, these values should be returned as empty strings.**

The `scraper` function is then included within a Scraper class, which extends `BaseScraper.py`.

## Easy scraping

Thanks to the phenomenal work of @catatonicChimp, a lot of the scraping can now be done by extending the BaseScraper class.

### 1. Duplicate the scraper template

For writing a new scraper, you can refer to and duplicate the template: `docs/scraper_template.py`.

### 2. Get the agenda page HTML

In the case of most councils, you will will be able to use the `self.fetch_with_requests(url)` method to return the agenda page html as output.

For more complex pages, you may need to write a Selenium script using the driver returned by `self.get_selenium_driver()`.

### 3. Use BeautifulSoup to get the agenda details

Load the HTML into BeautifulSoup like this:

```py
soup = BeautifulSoup(output, 'html.parser')
```

And then use the [BeautifulSoup documentation](https://www.crummy.com/software/BeautifulSoup/bs4/doc/) to navigate the HTML and grab the relevant elements and information.

You may also need to use regular expressions (regexes) to parse dates etc.

Luckily, ChatGPT is quite good at both BeautifulSoup and regexes. So it's recommended that you'll save a great deal of time feeding your HTML into ChatGPT, Github Copilot, or the shockingly reliable [Phind.com](https://www.phind.com) and iterating like that.

Once you have got the agenda download link and all other available, scrapeable information, return a ScraperReturn object.
