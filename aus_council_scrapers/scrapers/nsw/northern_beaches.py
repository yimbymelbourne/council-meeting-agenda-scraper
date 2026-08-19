import datetime
import json
import re
import urllib.parse

import pytz

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import TIMEZONES_BY_STATE

# Northern Beaches left InfoCouncil - northernbeaches.infocouncil.biz now 404s at
# every path - for Docs Published, a single-page app backed by a JSON API.
PORTAL_SLUG = "northernbeaches"
PORTAL_URL = f"https://docspublished.com.au/{PORTAL_SLUG}"
API_URL = "https://api.docassembler.com.au/api"

BUNDLE_REGEX = re.compile(r'src="([^"]*main-[A-Za-z0-9]+\.js)"')
BASE_HREF_REGEX = re.compile(r'<base[^>]+href="([^"]*)"')
BLOB_CONFIG_REGEX = re.compile(
    r'azureConnectionString:"(?P<base>[^"]+)"'
    r',azureContainerName:"(?P<container>[^"]+)"'
    r',azureSasToken:"(?P<sas>[^"]+)"'
)


@register_scraper
class NorthernBeachesScraper(BaseScraper):
    def __init__(self):
        council = "northern_beaches"
        state = "NSW"
        base_url = "https://www.northernbeaches.nsw.gov.au/"
        super().__init__(council, state, base_url)
        self.default_location = "Civic Centre, 7 Civic Drive, Dee Why"

    def scraper(self) -> list[ScraperReturn]:
        organisation = self._get_json(f"{API_URL}/organisation/{PORTAL_SLUG}")
        if not organisation:
            self.logger.error(f"No Docs Published organisation for {PORTAL_SLUG}")
            return []

        blob_config = self._blob_config()
        if not blob_config:
            self.logger.error("Could not read the Docs Published storage settings")
            return []

        documents = self._get_json(f"{API_URL}/documents/{organisation['Id']}") or []
        customer_key = organisation["Key"]

        results = []
        for document in documents:
            agenda = self._document_urls(
                blob_config,
                customer_key,
                document.get("AgendaAssembledDocFolderName"),
                document.get("AgendaDocumentFilePath"),
            )
            minutes = self._document_urls(
                blob_config,
                customer_key,
                document.get("MinutesAssembledDocFolderName"),
                document.get("MinutesDocumentFilePath"),
            )

            if not agenda and not minutes:
                continue

            local_start = self._local_start(document.get("MeetingDate"))

            results.append(
                ScraperReturn(
                    name=document.get("MeetingType") or document.get("DocumentTitle"),
                    date=local_start.date().isoformat() if local_start else None,
                    time=(
                        local_start.strftime("%I:%M %p").lstrip("0")
                        if local_start
                        else None
                    ),
                    webpage_url=PORTAL_URL,
                    agenda_url=agenda.get("pdf"),
                    minutes_url=minutes.get("pdf"),
                    agenda_html_url=agenda.get("html"),
                    minutes_html_url=minutes.get("html"),
                    download_url=agenda.get("pdf"),  # For backward compatibility
                    location=None,
                )
            )

        if not results:
            self.logger.info(f"{self.council_name} scraper found no meetings")
        else:
            self.logger.info(
                f"{self.council_name} scraper found {len(results)} meetings"
            )

        return results

    def _local_start(self, meeting_date):
        """Convert the API's MeetingDate to the council's local time.

        MeetingDate is UTC despite carrying no offset. Converting it is what
        makes the data line up: every meeting then starts at 6:00 or 6:30 PM,
        matching the times the council publishes, and the local date agrees with
        the date stamped into 137 of the 139 document filenames - the two
        stragglers are filenames typed as 2029 instead of 2019. Taking the date
        half of the raw value instead puts the evening meetings that were entered
        in UTC on the wrong day.
        """
        if not meeting_date:
            return None

        try:
            naive = datetime.datetime.fromisoformat(meeting_date)
        except ValueError:
            self.logger.warning(f"Unparseable MeetingDate {meeting_date!r}")
            return None

        timezone = pytz.timezone(TIMEZONES_BY_STATE[self.state.upper()])
        return pytz.utc.localize(naive).astimezone(timezone)

    def _get_json(self, url: str):
        """Fetch JSON through the fetcher so runs stay recordable."""
        try:
            body = self.fetcher.fetch_with_requests(url)
            return json.loads(body) if body else None
        except Exception as e:
            self.logger.error(f"Failed to fetch {url}: {e}")
            return None

    def _blob_config(self):
        """Read the document storage settings out of the portal's JS bundle.

        Documents live in Azure blob storage and need the container's read-only
        SAS token, which the portal ships in its bundle. The bundle name carries
        a build hash, so it is discovered from the page rather than hardcoded -
        that way a redeploy or a rotated token does not break the scraper.
        """
        try:
            shell = self.fetcher.fetch_with_requests(PORTAL_URL)
            bundle_match = BUNDLE_REGEX.search(shell)
            if not bundle_match:
                self.logger.error("Could not find the Docs Published JS bundle")
                return None

            # The portal is an Angular app served with <base href="/">, so its
            # relative script tags resolve against the site root, not the
            # council path. Getting this wrong is quiet rather than loud: unknown
            # paths return the app shell with a 200 instead of a 404.
            base_href = BASE_HREF_REGEX.search(shell)
            base_url = urllib.parse.urljoin(
                PORTAL_URL, base_href.group(1) if base_href else "/"
            )

            bundle = self.fetcher.fetch_with_requests(
                urllib.parse.urljoin(base_url, bundle_match.group(1))
            )
            config_match = BLOB_CONFIG_REGEX.search(bundle)
            if not config_match:
                self.logger.error("Could not find the storage settings in the bundle")
                return None

            return config_match.groupdict()
        except Exception as e:
            self.logger.error(f"Failed to read the storage settings: {e}")
            return None

    @staticmethod
    def _document_urls(blob_config, customer_key, folder_name, file_path) -> dict:
        """Build the storage URL for one document, mirroring the portal.

        Non-PDF papers are reported as the HTML rendition so the agenda URL
        always points at something the PDF pipeline can actually open.
        """
        if not folder_name or not file_path:
            return {}

        quoted = "/".join(
            urllib.parse.quote(part, safe="")
            for part in (customer_key, folder_name, file_path)
        )
        url = (
            f"{blob_config['base']}/{blob_config['container']}/"
            f"{quoted}{blob_config['sas']}"
        )

        return {"pdf" if file_path.lower().endswith(".pdf") else "html": url}
