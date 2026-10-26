"""Turning a SharePoint "Anyone with the link" share link into the file itself.

Some councils publish every paper as a SharePoint share link,
`https://<tenant>.sharepoint.com/:b:/s/<site>/<token>?e=<x>`. That URL is a
viewer, not the document. Adding `download=1` does not help a plain client:
it answers 302 to the file's library path and sets a guest `FedAuth` cookie,
and the library path answers 403 to any request that does not send the cookie
back. council-alerts downloads every document a scraper emits, so a URL that
works only with a cookie jar is not a document URL.

`/sites/<site>/_layouts/15/download.aspx?share=<token>` is. It answers 200
with `application/pdf` and the file's bytes on the first request, with no
redirect and no cookie (checked 26 Oct 2026 on Fraser Coast's and Mount
Magnet's tenants).

A file shared from someone's OneDrive rather than a team site is linked as
`https://<tenant>-my.sharepoint.com/:b:/g/personal/<user>/<token>`, and its
direct form is `/personal/<user>/_layouts/15/download.aspx?share=<token>` on
the same host. It answers the same way: 200 (206 to a Range request) with
`application/pdf`, no redirect and no cookie (checked 26 Oct 2026 on Huon
Valley's tenant, which files most of its papers this way).

A *folder* share (`/:f:/`) has no such form. The files in a shared folder can
be listed and read only with the guest cookie that redeeming the folder link
sets, and `download.aspx?share=<folder token>` returns an error page whatever
`UniqueId` or `SourceUrl` is added. So a paper linked only as a folder cannot
be emitted. Huon Valley links most of its agendas as folders, so its scraper
emits those meetings' minutes but not their agendas.

robots.txt on every `*.sharepoint.com` tenant is `User-Agent: *` /
`Disallow: /`. A scraper that emits these URLs is relying on a documented
robots.txt exception; see AGENTS.md before using this for a new council.
"""

from __future__ import annotations

import re
from typing import Optional

# `:b:` (PDF), `:w:` (Word) and the other one-letter viewer kinds are files;
# `:f:` is a folder and is deliberately not matched. Team sites (`/s/<site>`)
# and OneDrive (`/g/personal/<user>`) are handled, since those are what
# councils link.
_FILE_SHARE = re.compile(
    r"^https://(?P<host>[a-z0-9-]+\.sharepoint\.com)"
    r"/:[a-eg-z]:/(?:s/(?P<site>[^/?#]+)|g/personal/(?P<user>[^/?#]+))"
    r"/(?P<token>[A-Za-z0-9_-]+)"
    r"(?:[?#]|$)"
)


def file_share_download_url(href: str) -> Optional[str]:
    """The direct-download URL for a SharePoint file share link, or None.

    None for anything that is not a team-site or OneDrive file share link on
    a sharepoint.com tenant, including a folder share.
    """
    match = _FILE_SHARE.match(href.strip())
    if not match:
        return None
    if match["site"]:
        library = f"sites/{match['site']}"
    else:
        library = f"personal/{match['user']}"
    return (
        f"https://{match['host']}/{library}/_layouts/15/download.aspx"
        f"?share={match['token']}"
    )
