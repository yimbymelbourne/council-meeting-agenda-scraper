# Council Meeting Agenda Scraper

Check, download, and parse local council agendas for relevant housing and planning matters.

Users can easily set up notification functionality to be alerted by email (or: to-be-implemented, Discord) when new agendas are released.

This enables YIMBY Melbourne and other organisations to keep easy track of relevant Council activities.

## List of functioning scrapers

- boroondara
- darebin
- maribyrnong
- melbourne
- merribek
- moonee_valley
- port_phillip
- whitehorse

A table of Melbourne-based scraper details, including links and current status, can be found [in the docs](https://github.com/yimbymelbourne/council-meeting-agenda-scraper/blob/main/docs/councils.md) (`docs/councils.md`)

A text dump of National scrapers can be found [in the docs](https://github.com/yimbymelbourne/council-meeting-agenda-scraper/blob/main/docs/national_councils_dump.txt) (`docs/national_councils_dump.txt`)

[Write a Scraper! (Instructions)](#writing-a-scraper)

# Setup

## Development

1. Setup and activate the Python environment of your choosing.

2. Ensure you have `poetry` installed (e.g. with `pip install poetry`).

3. Run `poetry shell` to ensure you've activated the correct virtual env.

4. Run `poetry install` to install dependencies.

# Running the application

Within your environment, run: `python3 main.py > "output/scrapers_output_$(date +%Y-%m-%d).txt"`

This will generate the scraper results within a text file for your convenience, as well as writing key results to `agendas.db`.

## .env & Email client (optional)

In the `.env.example` file, there is the basic variable GMAIL_FUNCTIONALITY.

This functionality is turned off by default. If you want to use the email sending features here, then you'll need to include your Gmail authentication details in a `.env` file.

This may require setting up an App-specific password, for which [you can find setup instructions here](https://support.google.com/accounts/answer/185833?visit_id=638406540644584172-3254681882&p=InvalidSecondFactor&rd=1).

This functionality is optional, and the app should work fine without this setup.

# Writing a scraper

Melbourne has many councils! As such, we need many scrapers!

A list of most Melbourne councils, including links to their agenda webpages, can be found on the [YIMBY Melbourne website](https://www.yimbymelbourne.org.au/local-action).

Check the current issue list, or create your own. Then, build a scraper and contribute to YIMBY Melbourne's mission to create housing abundance for all Melburnians!

## How scrapers work

Scrapers are contained within the `scrapers/` folder.

A scraper should be able to reliably find the most recent agenda on a Council's website. Once that link is found, it is checked against an existing database—if the link is new, then the agenda is downloaded, scanned, and a notification is sent.

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

The scraper function is then included within a Council object at the bottom of the file. At time of open-sourcing, `scrapers/maribyrnong.py`, exported the following object:

```py
maribyrnong = Council(
  name='Maribyrnong', # council name
  scraper=scraper, # custom scraper function, called during iterative loop
)
```

Working Councils should then be imported into `scrapers/__init__.py`.

The `main.py` script then iterates through these councils using the `processor()` function. For each new agenda found, the results will be logged.

## Easy scraping

This repository is not prescriptive with how scrapers should be written.

That said, it's always nice to limit project dependencies, so we recommend the following technologies:

- [Selenium](https://www.selenium.dev/documentation/), for headless web navigation; and
- [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/bs4/doc/), for parsing static html

The pipeline is this: you use Selenium to get the right html, and then use BeautifulSoup to find the agenda link within it.

### Selenium

The best thing about Selenium is that it has its own [Integrated Development Environment](https://www.selenium.dev/selenium-ide/) for Chromium & Firefox browsers.

The IDE lets you just use a website, and records all your actions. You can then export those actions straight into Python.

This means that if you need to, for instance, expand an accordion in order for your agenda to appear, Selenium can record those actions and then perform them every time the scraper runs.

Just remember to run your exported Selenium code in headless mode. To do so, configure your driver like this:

```py
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

#...

chrome_options = Options()
chrome_options.add_argument("--headless")
driver = webdriver.Chrome(options=chrome_options)
```

When navigation is complete, return the HTML from your selenium driver:

```py
output = driver.page_source
```

### BeautifulSoup

Load the HTML into BeautifulSoup like this:

```py
soup = BeautifulSoup(output, 'html.parser')
```

And then use the BeautifulSoup documentation to navigate the HTML and grab the relevant elements and information.

You may also need to use regular expressions (regexes) to parse dates etc.

Luckily, ChatGPT is quite good at both BeautifulSoup and regexes. So it's recommended that you'll save a great deal of time feeding your HTML into ChatGPT, Github Copilot, or the shockingly reliable [Phind.com](https://www.phind.com) and iterating like that.

Finally, ensure your `scraper()` function returns a `ScraperReturn` dataclass.

### Adding to the app

Finally, once you're confident your scraper works, ensure it is imported into `scrapers/__init__.py`.

Then, file a pull request, and it'll be merged upon successful review.
