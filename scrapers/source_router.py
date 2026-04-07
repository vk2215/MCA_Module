"""
scrapers/source_router.py
==========================
Routes a (reference, source) pair to the correct scraper function.

HOW TO ADD A NEW SOURCE
-----------------------
1. Create  scrapers/<source>_scraper.py  with a public function:
       def search_and_download_<source>_pdf(reference: str) -> dict | None
       # dict shape: {"filepath": str, "source_pdf_url": str}

2. Import it here and add one line to SOURCE_REGISTRY:
       "SourceName": search_and_download_<source>_pdf,

That's it — main.py does not need any changes.

FALLBACK
--------
If no scraper is registered for a source, or if the registered scraper
returns None, `download_reference_pdf` returns None.
A fallback handler can be wired in by setting FALLBACK_FN at the bottom
of this file (or patching it at runtime before calling the router).
"""

import os
import re
import logging
from typing import Callable
from pathlib import Path
from scrapers.sebi_scraper import search_and_download_sebi_pdf
from scrapers.indiacode_scraper import search_and_download_indiacode_pdf
from scrapers.web_searcher import google_fallback_download

logger = logging.getLogger("ReferenceExtraction")


# Registry  —  
SOURCE_REGISTRY: dict[str, Callable[[str], dict | None]] = {
    "sebi":       search_and_download_sebi_pdf,
    "indiacode":  search_and_download_indiacode_pdf,
    # "amfi":    search_and_download_amfi_pdf,   # coming soon
    # "rbi":     search_and_download_rbi_pdf,    # coming soon
    # "mca":     search_and_download_mca_pdf,    # coming soon
}

# ---------------------------------------------------------------------------
# Fallback  —  called when no scraper is found or the scraper returns None.
# Set to a function with signature  (reference: str) -> dict | None
# dict shape: {"filepath": str, "source_pdf_url": str}
# Leave as None to skip the fallback step entirely.
# ---------------------------------------------------------------------------
FALLBACK_FN: Callable[[str, str | None], dict | None] = google_fallback_download


def normalize_reference_name(name: str) -> str:
    """Remove things like '(15 of 1992)' or '(42 of 1956)' from the name."""
    if not name:
        return name
    # Strip (Number of Year) patterns
    res = re.sub(r'\s*\(\s*\d+\s+of\s+\d+\s*\)', '', name)
    return res.strip()

def download_reference_pdf(reference: str, source: str | None) -> dict | None:
    """
    Look up the correct scraper for `source` and attempt to download
    the PDF for `reference`.  Falls back to FALLBACK_FN if:
      - No scraper is registered for the source, OR
      - The registered scraper returns None (PDF not found).

    Returns {"filepath": str, "source_pdf_url": str} or None.
    """
    # ── 0. Handle Multiple References (`|||`) ─────────────────────────────────
    if "|||" in reference:
        refs = [r.strip() for r in reference.split("|||") if r.strip()]
        results = []
        logger.info(f"Source Router: Found multiple references separated by |||, splitting into {len(refs)} items.")
        for r in refs:
            res = download_reference_pdf(r, source)
            if res:
                results.append(res)
        if not results:
            return None
        return {
            "filepath":       " ||| ".join(r["filepath"] for r in results),
            "source_pdf_url": results[0]["source_pdf_url"],
        }

    # ── 1. Check if we already have it locally ──────────────────────────────
    candidates = [reference, normalize_reference_name(reference)]
    local_path = None
    for cand in candidates:
        safe   = re.sub(r'[\\/*?:"<>|]', "", cand)
        safe   = re.sub(r'\s+', "_", safe.strip())[:120]
        if safe:
            local_candidate = os.path.join("repository", f"{safe}.pdf")
            if os.path.exists(local_candidate):
                local_path = local_candidate
                logger.info(f"Source Router: found local copy for '{cand}' — {local_candidate}")
                break

    # ── 2. Routing Logic (Search for URL regardless of local file) ──────────
    search_ref = normalize_reference_name(reference)
    source_key   = (source or "").strip().lower()
    scraper_fn   = SOURCE_REGISTRY.get(source_key)

    found_url = None

    if scraper_fn:
        logger.info(f"Source Router: routing '{search_ref}' → scraper for '{source}'")
        result = scraper_fn(search_ref)
        if result:
            found_url = result.get("source_pdf_url")
            if not local_path:
                local_path = result.get("filepath")
        else:
            logger.warning(f"Source Router: scraper for '{source}' found nothing — trying fallback")
    else:
        logger.warning(f"Source Router: no scraper registered for source='{source}' — trying fallback")

    # ── Fallback ──────────────────────────────────────────────────────────────
    if not found_url and FALLBACK_FN:
        logger.info(f"Source Router: invoking fallback for '{search_ref}'")
        result = FALLBACK_FN(search_ref, source)
        if result:
            found_url = result.get("source_pdf_url")
            if not local_path:
                local_path = result.get("filepath")

    # ── Final Return ──────────────────────────────────────────────────────────
    if local_path:
        return {
            "filepath": local_path,
            "source_pdf_url": found_url or ""
        }

    logger.warning(f"Source Router: no file or URL found for '{search_ref}'")
    return None
    return None