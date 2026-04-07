"""
scrapers/indiacode_scraper.py
==============================
Searches indiacode.nic.in for a regulation/act PDF matching a given
reference title, downloads it, and saves it to the repository directory.

Usage from source_router:
    from scrapers.indiacode_scraper import search_and_download_indiacode_pdf
    pdf_path = search_and_download_indiacode_pdf("Registration Act, 1908")
"""

import os
import re
import logging
import requests
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup

logger = logging.getLogger("ReferenceExtraction")

# Constants
# ---------------------------------------------------------------------------
INDIACODE_SEARCH_URL = "https://www.indiacode.nic.in/handle/123456789/1362/simple-search"
REPO_DIR             = "repository"
MAX_PAGES            = 2    # IndiaCode pagination guard
MAX_RESULTS          = 3    # stop after this many candidate links


# Public API
# ===========================================================================
'''
def search_and_download_indiacode_pdf(reference: str) -> str | None:
    """
    Search indiacode.nic.in for a document matching `reference`,
    download the first valid PDF, and save it to REPO_DIR.
    """
    logger.info(f"IndiaCode Scraper: searching for — {reference}")
    Path(REPO_DIR).mkdir(parents=True, exist_ok=True)

    session      = _create_session()
    search_query = _clean_search_query(reference)
    pdf_links    = _collect_pdf_links(session, search_query, reference)

    if not pdf_links:
        logger.warning(f"IndiaCode Scraper: no PDF links found for — {reference}")
        return None

    for pdf_url in pdf_links:
        local_path = _download_pdf(session, pdf_url, reference)
        if local_path:
            logger.info(f"IndiaCode Scraper: saved PDF to — {local_path}")
            return local_path

    logger.warning(f"IndiaCode Scraper: all download attempts failed for — {reference}")
    return None
'''
# Change the return type hint from str | None to dict | None
def search_and_download_indiacode_pdf(reference: str) -> dict | None:
    """
    Search indiacode.nic.in for a document matching `reference`,
    download the first valid PDF, and save it to REPO_DIR.
    
    Returns: {"filepath": str, "source_pdf_url": str} or None
    """
    logger.info(f"IndiaCode Scraper: searching for — {reference}")
    Path(REPO_DIR).mkdir(parents=True, exist_ok=True)

    session      = _create_session()
    search_query = _clean_search_query(reference)
    pdf_links    = _collect_pdf_links(session, search_query, reference)

    if not pdf_links:
        logger.warning(f"IndiaCode Scraper: no PDF links found for — {reference}")
        return None

    for pdf_url in pdf_links:
        # result will now be the dictionary {"filepath": ..., "source_pdf_url": ...}
        result = _download_pdf(session, pdf_url, reference)
        if result:
            logger.info(f"IndiaCode Scraper: saved PDF to — {result['filepath']}")
            return result

    logger.warning(f"IndiaCode Scraper: all download attempts failed for — {reference}")
    return None

# ===========================================================================
# Internal helpers
# ===========================================================================

def _create_session() -> requests.Session:
    """Create a pre-configured requests session for IndiaCode."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return session


def _clean_search_query(reference: str) -> str:
    """Strip only the act-number suffix (e.g. '(16 of 1908)') but keep the year."""
    query = re.sub(r'\s*\(\d+\s+of\s+\d+\)', '', reference)  # remove "(16 of 1908)"
    return query.strip()


def _is_result_title_match(reference: str, result_title: str) -> bool:
    """
    Check whether a search result title is a good match for the reference.

    Strategy:
      1. Hard year check — year must match exactly.
      2. Build keyword list from reference — exclude years (already checked)
         and deduplicate (e.g. "2013" in "Act 2013 (18 of 2013)" appears
         twice; without dedup it inflates the denominator and lets wrong
         acts with the same year pass).
      3. Require at least 1 non-year keyword to hit (no pure-year matches).
      4. Require >= 60% keyword overlap.
    """
    def _norm(text):
        t = (text or "").lower()
        t = re.sub(r'[()\[\],.;:\'"\`]', " ", t)
        return re.sub(r'\s+', " ", t).strip()

    ref_norm    = _norm(reference)
    result_norm = _norm(result_title)

    # ── Step 1: Hard year check ─────────────────────────────────────────────
    year_m = re.search(r'\b(19|20)\d{2}\b', reference)
    if year_m:
        if year_m.group(0) not in result_norm:
            return False

    # ── Step 2: Build deduplicated keyword list — years excluded ───────────
    stop     = {"the", "of", "to", "and", "in", "for", "a", "an", "by", "or", "as"}
    year_pat = re.compile(r'\d{4}')

    all_words = [
        w for w in ref_norm.split()
        if len(w) >= 3
        and w not in stop
        and not year_pat.fullmatch(w)   # skip year tokens — already checked above
    ]
    ref_words = list(dict.fromkeys(all_words))   # deduplicated, order preserved

    if not ref_words:
        # Only year in the reference — year already matched, accept
        return True

    # ── Step 3: Score overlap ───────────────────────────────────────────────
    # IndiaCode titles may be concatenated CamelCase (e.g. "TheCompaniesAct,1956")
    # or spaced ("The Companies Act, 1956").
    # Tokenise the ORIGINAL title (before lowercasing) so CamelCase split works.
    # Note: result_norm is all-lowercase so CamelCase split is a no-op there.
    def _tokenise(text):
        """Split CamelCase then tokenise on non-alpha chars. Returns lowercase token set."""
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)   # split CamelCase
        spaced = re.sub(r"[^a-zA-Z]+", " ", spaced)             # drop non-alpha
        return set(spaced.lower().split())

    title_tokens = _tokenise(result_title)   # use ORIGINAL title for tokenisation

    def _word_hit(w):
        if w in title_tokens:
            return True
        # Handle simple plurals: "trusts" -> "trust"
        if w.endswith("s") and len(w) > 4 and w[:-1] in title_tokens:
            return True
        return False

    hits  = sum(1 for w in ref_words if _word_hit(w))
    ratio = hits / len(ref_words) if ref_words else 1.0
    logger.debug(
        f"IndiaCode Scraper: title='{result_title}' → "
        f"hits={hits}/{len(ref_words)} ({ratio:.0%}) "
        f"keywords={ref_words}"
    )

    # ── Step 4: Required Key Terms Check (Anti-Collision) ───────────────────
    # Identify unique words that MUST be in the title (e.g. if I ask for "Companies",
    # don't accept "Manual Scavengers").
    important_keywords = [
        w for w in ref_words 
        if w not in {"act", "regulation", "code", "rule", "rules", "regulations", "short", "title"}
    ]
    if important_keywords:
        # Require at least one of the specific subject words to be present
        if not any(kw in title_tokens for kw in important_keywords):
            logger.debug(f"IndiaCode Scraper: rejecting '{result_title}' - missing key subject words {important_keywords}")
            return False

    return ratio >= 0.50


def _is_valid_act_pdf_url(url: str) -> bool:
    """
    Allow only act-like IndiaCode PDF targets.
    Blocks help, userGuide, and other site-navigation documents.
    """
    lower = (url or "").lower()
    if "indiacode.nic.in" not in lower:
        return False
    # Block known non-act paths and site-wide help assets
    if any(x in lower for x in ["/help/", "userguide", "user-guide", "manual", "faq", "guide", "tip", "search-tips"]):
        logger.debug(f"IndiaCode Scraper: skipping non-act URL: {url}")
        return False
    # Must point to a PDF or bitstream
    return lower.endswith(".pdf") or "/bitstream/" in lower


def _collect_pdf_links(
    session: requests.Session, search_query: str, reference: str
) -> list:
    """
    Run the IndiaCode search and collect direct PDF / bitstream URLs
    that match `reference`. Handles pagination up to MAX_PAGES.
    """
    try:
        seed_resp = session.get(
            INDIACODE_SEARCH_URL,
            params={"query": search_query, "searchradio": "acts", "btngo": ""},
            timeout=10,
        )
        seed_resp.raise_for_status()
        logger.debug(f"IndiaCode Scraper: seed URL resolved to: {seed_resp.url}")
    except Exception as e:
        logger.debug(f"IndiaCode Scraper: seed request failed: {e}")
        return []

    pages_to_visit = [seed_resp.url]
    visited        = set()
    pdf_links      = []
    seen           = set()

    while pages_to_visit and len(visited) < MAX_PAGES:
        page_url = pages_to_visit.pop(0)
        if page_url in visited:
            continue
        visited.add(page_url)

        try:
            resp = session.get(page_url, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            logger.debug(f"IndiaCode Scraper: page fetch failed {page_url}: {e}")
            continue

        soup = BeautifulSoup(resp.content, "html.parser")

        # ── Direct PDF links on the search results page ───────────────────────
        for a_tag in soup.find_all("a", href=True):
            href     = a_tag.get("href", "").strip()
            full_url = urljoin("https://www.indiacode.nic.in", href)
            if not _is_valid_act_pdf_url(full_url):
                continue
            if full_url not in seen:
                seen.add(full_url)
                pdf_links.append(full_url)
                logger.debug(f"IndiaCode Scraper: found candidate PDF: {full_url}")
                if len(pdf_links) >= MAX_RESULTS:
                    return pdf_links

        # ── Resolve item detail pages — read title from table row, not link text ──
        # IndiaCode search results are a 4-column table:
        #   col-0: Date | col-1: Act No | col-2: Short Title | col-3: "View..." link
        # We iterate rows, read col-2 as the title, score it, then follow col-3's link.
        table = soup.find("table", class_=lambda c: c and "table" in c)
        if table:
            for row in table.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) < 4:
                    continue

                # col-2 = act short title, col-3 = View link
                row_title = cols[2].get_text(strip=True)
                view_link = cols[3].find("a", href=True)
                if not view_link or not row_title:
                    continue

                href = view_link.get("href", "").strip()
                if "/handle/123456789/" not in href:
                    continue

                logger.debug(
                    f"IndiaCode Scraper: result row title='{row_title}'"
                )
                if not _is_result_title_match(reference, row_title):
                    logger.debug(
                        f"IndiaCode Scraper: skipping non-matching item '{row_title}'"
                    )
                    continue

                logger.info(f"IndiaCode Scraper: matched — '{row_title}'")
                item_url = urljoin("https://www.indiacode.nic.in", href)
                try:
                    item_resp = session.get(item_url, timeout=10)
                    item_resp.raise_for_status()
                    item_soup = BeautifulSoup(item_resp.content, "html.parser")
                    logger.debug(f"IndiaCode Scraper: scanning item page: {item_url}")
                    for bit_tag in item_soup.find_all("a", href=True):
                        bit_href = bit_tag.get("href", "").strip()
                        full_url = urljoin("https://www.indiacode.nic.in", bit_href)
                        if not _is_valid_act_pdf_url(full_url):
                            continue
                        if full_url not in seen:
                            seen.add(full_url)
                            pdf_links.append(full_url)
                            logger.debug(f"IndiaCode Scraper: found bitstream PDF: {full_url}")
                            if len(pdf_links) >= MAX_RESULTS:
                                return pdf_links
                        break   # one PDF per item page is enough
                except Exception as e:
                    logger.debug(f"IndiaCode Scraper: item page error {item_url}: {e}")

        # ── Follow tokenised next-page links ─────────────────────────────────
        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "").strip()
            if "simple-search" in href.lower() and "page-token=" in href.lower():
                next_page = urljoin("https://www.indiacode.nic.in", href)
                if next_page not in visited and next_page not in pages_to_visit:
                    pages_to_visit.append(next_page)

    logger.debug(f"IndiaCode Scraper: total valid PDF candidates found: {len(pdf_links)}")
    return pdf_links


def _download_pdf(session: requests.Session, pdf_url: str, reference: str) -> dict | None:
    """Download a PDF from pdf_url and save it to REPO_DIR."""
    try:
        logger.info(f"IndiaCode Scraper: downloading — {pdf_url}")
        resp = session.get(pdf_url, timeout=30, allow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "").lower()
        if not ("application/pdf" in content_type or "pdf" in content_type or resp.content.startswith(b"%PDF")):
            logger.warning(f"IndiaCode Scraper: response is not a PDF — {pdf_url}")
            return None

        safe_name = re.sub(r'[\\/*?:"<>|]', "", reference)
        safe_name = re.sub(r'\s+', "_", safe_name.strip())[:120]
        filename  = f"{safe_name}.pdf" if safe_name else f"indiacode_{hash(pdf_url) % 100000}.pdf"
        filepath  = os.path.join(REPO_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(resp.content)

        #return filepath
        return {"filepath": filepath, "source_pdf_url": pdf_url}

    except Exception as e:
        logger.error(f"IndiaCode Scraper: download failed for {pdf_url}: {e}")
        return None