"""Download filing PDFs once (cached on disk) and extract their text."""
import hashlib
import os

import pymupdf
import requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data", "cache", "pdfs")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
}


def get_pdf_path(url):
    """Return the local path of the PDF, downloading it the first time."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    name = hashlib.sha1(url.encode("utf-8")).hexdigest() + ".pdf"
    path = os.path.join(CACHE_DIR, name)
    if not os.path.exists(path):
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        with open(path, "wb") as f:
            f.write(response.content)
    return path


def get_pdf_text(url, max_pages=None):
    """Return the text of the PDF ('' if it can't be read, e.g. a scanned image)."""
    if not url or not url.lower().endswith(".pdf"):
        return ""
    try:
        path = get_pdf_path(url)
        doc = pymupdf.open(path)
    except Exception as e:
        print("  could not read PDF", url, "->", e)
        return ""

    pages = []
    for page_number in range(len(doc)):
        if max_pages is not None and page_number >= max_pages:
            break
        pages.append(doc[page_number].get_text())
    doc.close()
    return "\n".join(pages)
