"""Step 1 - data acquisition from the MTAK REAL-MS EPrints repository."""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import urllib.parse

import requests
from bs4 import BeautifulSoup

EPRINT_URL = "https://real-ms.mtak.hu/80/"
JSON_URL = "https://real-ms.mtak.hu/cgi/export/eprint/80/JSON/real-ms-eprint-80.json"
TIMEOUT = 120
CHUNK = 1 << 20


def discover_pdf_links(page_url: str = EPRINT_URL) -> list[str]:
    """Parse the EPrints landing page and return every PDF segment link, in order."""
    response = requests.get(page_url, timeout=TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = urllib.parse.urljoin(page_url, anchor["href"])
        if href.lower().endswith(".pdf") and "ThumbnailVersion" not in href and href not in links:
            links.append(href)
    return links


def describe_documents() -> list[dict]:
    """Return the repository's own document metadata (resolution and access level)."""
    response = requests.get(JSON_URL, timeout=TIMEOUT)
    response.raise_for_status()
    documents = []
    for document in response.json().get("documents", []):
        documents.append(
            {
                "filename": document.get("main"),
                "security": document.get("security"),
                "description": document.get("formatdesc"),
                "filesize": document["files"][0]["filesize"] if document.get("files") else None,
            }
        )
    return documents


def download(url: str, target_dir: pathlib.Path) -> pathlib.Path | None:
    """Download a single PDF segment. Returns None when access is denied."""
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / pathlib.PurePosixPath(urllib.parse.urlparse(url).path).name

    with requests.get(url, stream=True, timeout=TIMEOUT) as response:
        if response.status_code in (401, 403):
            print(f"  skipped (HTTP {response.status_code}, restricted): {url}", file=sys.stderr)
            return None
        response.raise_for_status()
        digest = hashlib.md5()
        with destination.open("wb") as handle:
            for chunk in response.iter_content(CHUNK):
                handle.write(chunk)
                digest.update(chunk)

    if destination.read_bytes()[:5] != b"%PDF-":
        print(f"  discarded (not a PDF payload): {url}", file=sys.stderr)
        destination.unlink()
        return None

    print(f"  {destination.name}  {destination.stat().st_size / 1e6:.1f} MB  md5={digest.hexdigest()}")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/raw"))
    args = parser.parse_args()

    for document in describe_documents():
        print(f"repository document: {document['filename']} [{document['security']}] {document['description']}")

    links = discover_pdf_links()
    print(f"discovered {len(links)} PDF segment(s)")
    downloaded = [path for url in links if (path := download(url, args.out))]

    if not downloaded:
        print("no PDF segments could be downloaded", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
