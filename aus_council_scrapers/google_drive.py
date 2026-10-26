"""Council papers shared from Google Drive, as URLs a plain client can download.

A Drive file link, `drive.google.com/file/d/<id>/view`, is a viewer page.
`drive.google.com/uc?export=download&id=<id>` is the file: it answers 303 to
`drive.usercontent.google.com/download?id=<id>&export=download`, which
answers 200 with the bytes as an attachment (`Content-Disposition:
attachment; filename="... .pdf"`), no login and no cookie. Drive labels the
body `application/octet-stream`, not `application/pdf`, whatever the file
is (checked 26 Oct 2026 on Huon Valley's and Mount Marshall's files). A file
the owner has not shared publicly redirects to a Google sign-in page
instead, and is not a document URL.

A folder link, `drive.google.com/drive/folders/<id>`, is a server-rendered
page listing each file as a `tr[data-id]` row with its name in `<strong>`.

robots.txt, checked 26 Oct 2026: drive.google.com allows a list of prefixes
(`/file`, `/drive/` and others), sets `Crawl-delay: 1` and ends `Disallow:
/`, so `/uc` is disallowed and `/drive/folders/` is allowed;
drive.usercontent.google.com is `User-agent: *` / `Disallow: /`. Emitting or
fetching a `/uc` link relies on a documented robots.txt exception; see
AGENTS.md before using this for a new council. The per-host throttle
(`FETCH_DELAY`, 2 s by default) already spaces requests further apart than
the crawl delay.
"""

from __future__ import annotations

import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

DRIVE = "https://drive.google.com"
FILE_ID = re.compile(r"drive\.google\.com/(?:file/d/|open\?id=)([\w-]{20,})")
FOLDER_ID = re.compile(r"drive\.google\.com/drive/(?:u/\d+/)?folders/([\w-]{20,})")


def download_url(file_id: str) -> str:
    """The direct download for a Drive file id."""
    return f"{DRIVE}/uc?export=download&id={file_id}"


def folder_files(fetcher, folder_id: str) -> Optional[list[tuple[str, str]]]:
    """(file id, name) for each entry in a shared folder, None if it is gone.

    Sub-folders are listed too, by their names; the caller picks by name.
    A 404 (the council deleted or unshared the folder) is None. Anything
    else, a block or a timeout, raises, so a bad night fails the council
    rather than losing papers.
    """
    try:
        html = fetcher.fetch_with_requests(f"{DRIVE}/drive/folders/{folder_id}")
    except requests.HTTPError as error:
        if "404" not in str(error):
            raise
        return None
    soup = BeautifulSoup(html, "html.parser")
    files = []
    for row in soup.select("tr[data-id]"):
        name = row.find("strong")
        if name:
            files.append((row["data-id"], name.get_text(strip=True)))
    return files
