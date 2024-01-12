# agenda_getter

A method of getting and scraping council agendas to streamline housing abundance advocacy.

# Setup

## Development

1. Setup and activate the Python environment of your choosing.

2. Ensure you have `poetry` installed (e.g. with `pip install poetry`).

3. Run `poetry shell` to ensure you've activated the correct virtual env.

4. Run `poetry install` to install dependencies.

## .env & Email client (optional)

In the `.env.example` file, there is the basic variable GMAIL_FUNCTIONALITY. It is set to 0 by default. If you want to use the email sending features here, then you'll need to include your Gmail authentication details in a `.env` file.

This may require setting up an App-specific password, for which [you can find setup instructions here](https://support.google.com/accounts/answer/185833?visit_id=638406540644584172-3254681882&p=InvalidSecondFactor&rd=1).

This functionality is optional, and the app should work fine without this setup.

# Running the application

`python3 main.py`

# Writing a scraper

Currently, each council in the `scrapers/` directory should export a dict of this shape:

```py
council_name = {
  'council': 'Council Name',
  'regex_list': ['a list of regex', 'statements for matching'],
  'scraper': scraper_function(),
}
```

This data is then accessed by the `processor()` function which takes the above dict as an input.
