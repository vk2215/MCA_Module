"""
scrapers/web_searcher.py
=========================
DuckDuckGo-powered PDF fallback using the `ddgs` library.

Workflow:
  1. Search DuckDuckGo with the reference title (using DDGS library
     which handles internal DDG state without needing a real browser)
  2. Prioritise direct .pdf hits and trusted regulatory domains (sebi.gov.in etc.)
  3. Visit each candidate URL to find a PDF link on the page
  4. Download and save the first valid PDF found

Install requirement:
    pip install ddgs

Usage (set as FALLBACK_FN in source_router.py):
    from scrapers.web_searcher import google_fallback_download
    FALLBACK_FN = google_fallback_download
"""

import os
import re
import logging
import requests
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup

logger = logging.getLogger("ReferenceExtraction")

REPO_DIR         = "repository"
MAX_RESULTS      = 5   # how many DDG results to try per query

# Domains we trust — sort these to the top of results
TRUSTED_DOMAINS = [
    "sebi.gov.in",
    "indiacode.nic.in",
    "rbi.org.in",
    "amfiindia.com",
    "mca.gov.in",
    "incometax.gov.in",
    "irdai.gov.in",
]

# Domains we never want PDFs from
EXCLUDED_DOMAINS = [
    "wikipedia", "taxmann", "taxguru", "cleartax", "moneycontrol",
    "livemint", "economictimes", "youtube", "facebook", "twitter",
    "instagram", "linkedin", "quora", "bcasonline", "lawaudience",
    "conventuslaw", "indiafreenotes", "mbaknol", "blog", "journal",
    "article", "academia", "researchgate", "ssrn", "ipleaders",
    "mondaq", "barandbench", "livelaw", "legalserviceindia",
]


# ===========================================================================
# Public API
# ===========================================================================

def google_fallback_download(reference: str, source: str | None = None) -> dict | None:
    """
    Search DuckDuckGo (via the ddgs library) for `reference`,
    visit the top results, and download the first valid PDF found.
    Returns the local file path or None.
    """
    logger.info(f"Web Searcher (fallback): DDG search for — {reference}")
    Path(REPO_DIR).mkdir(parents=True, exist_ok=True)

    candidate_urls = _ddg_search(reference, source)
    if not candidate_urls:
        logger.warning(f"Web Searcher: no DDG results for — {reference}")
        return None

    session = _create_session()

    for url in candidate_urls:
        logger.info(f"Web Searcher: trying — {url}")
        if _looks_like_pdf_url(url):
            # Direct PDF URL: verify it likely refers to the right document
            # before downloading (avoids saving circular/announcement PDFs).
            if _pdf_url_matches_reference(url, reference):
                result = _download_pdf(session, url, reference)
            else:
                logger.debug(f"Web Searcher: PDF URL keyword mismatch, skipping {url}")
                result = None
        else:
            # HTML page: visit and check page title before extracting PDF link
            result = _extract_and_download_pdf(session, url, reference)
        if result:
            return result

    logger.warning(f"Web Searcher: no PDF found for — {reference}")
    return None


# ===========================================================================
# DDG search
# ===========================================================================

def _ddg_search(reference: str, source: str | None = None) -> list[str]:
    """
    Run DDG queries scoped to the right domain based on source.
    - source=SEBI      → search site:sebi.gov.in first
    - source=Indiacode → search site:indiacode.nic.in first
    - source=None      → try both trusted domains then general search
    """
    try:
        from ddgs import DDGS
    except ImportError:
        logger.error("Web Searcher: 'ddgs' library not installed. Run: pip install ddgs")
        return []

    seen: set[str] = set()
    urls: list[str] = []

    # Build queries based on source domain
    source_key = (source or "").strip().lower()
    if source_key == "sebi":
        primary_domain = "sebi.gov.in"
    elif source_key == "indiacode":
        primary_domain = "indiacode.nic.in"
    elif source_key == "rbi":
        primary_domain = "rbi.org.in"
    elif source_key == "mca":
        primary_domain = "mca.gov.in"
    else:
        primary_domain = None

    # Queries: primary domain scoped first, then general
    # Order matters: search without filetype:pdf first, because SEBI hosts their regulations 
    # strictly behind HTML wrapper files, and searching for naked PDFs returns random unrelated attachments
    queries = []
    
    is_act = bool(re.search(r'\bact\b', reference, re.IGNORECASE))
    
    if primary_domain:
        queries.append(f"\"{reference}\" site:{primary_domain}")
        # Add regulatory keyword boost to push out random company reports (unless it's an Act)
        if not is_act:
            if "sebi" in primary_domain:
                queries.append(f"\"{reference}\" regulations site:{primary_domain}")
            else:
                queries.append(f"\"{reference}\" notified site:{primary_domain}")
        queries.append(f"\"{reference}\" filetype:pdf site:{primary_domain}")
    else:
        # Search official domains first
        queries.append(f"\"{reference}\" site:sebi.gov.in")
        queries.append(f"\"{reference}\" site:indiacode.nic.in")
        queries.append(f"\"{reference}\" site:mca.gov.in")
    queries.append(f"\"{reference}\"")  # broad fallback

    for query in queries:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=MAX_RESULTS))
            for r in results:
                href = r.get("href", "").strip()
                if not href or href in seen:
                    continue
                lower = href.lower()
                if any(excl in lower for excl in EXCLUDED_DOMAINS):
                    continue
                seen.add(href)
                urls.append(href)
        except Exception as e:
            logger.debug(f"Web Searcher: DDG query failed '{query[:50]}': {e}")

        if urls:
            break  # site-scoped search found something — no need for broad query

    # Sort results:
    #   1. /legal/regulations/ HTML pages  ← SEBI's canonical regulation pages
    #   2. Named regulation PDFs (filename contains reference keywords)
    #   3. Other trusted-domain HTML pages
    #   4. Numeric-ID attachdoc PDFs (circulars, reports — very last resort)
    def _rank(url: str) -> tuple:
        import re as _re
        lower = url.lower()
        is_regulation_html = "/legal/regulations/" in lower
        is_numeric_pdf     = bool(_re.search(r"/\d{10,}(?:_\d+)?\.pdf", lower))
        is_pdf             = lower.split("?")[0].endswith(".pdf")
        is_trusted = next((i for i, d in enumerate(TRUSTED_DOMAINS) if d in lower), len(TRUSTED_DOMAINS))
        if is_regulation_html:
            priority = 0         # best: canonical SEBI regulation page
        elif is_pdf and not is_numeric_pdf:
            priority = 1         # named PDF (like AIFregulations2012_p.pdf)
        elif not is_pdf:
            priority = 2         # other HTML pages
        else:
            priority = 9         # numeric attachdoc PDFs — last resort
        return (priority, is_trusted)

    urls.sort(key=_rank)
    logger.info(f"Web Searcher: DDG candidates: {urls[:MAX_RESULTS]}")
    return urls[:MAX_RESULTS]


# ===========================================================================
# PDF extraction from a page
# ===========================================================================

def _extract_and_download_pdf(
    session: requests.Session, url: str, reference: str
) -> dict | None:
    """Visit a page, verify it's about the right document, then find + download its PDF."""
    try:
        resp = session.get(url, timeout=15, allow_redirects=True)
    except requests.exceptions.ConnectionError as ce:
        logger.warning(f"Web Searcher: Connection error on {url} - trying crawl4ai HTML fallback. ({ce})")
        # --- Fallback for HTML ---
        try:
            from scrapers.crawl4ai_downloader import fallback_get_html, fallback_download_pdf
            html = fallback_get_html(url)
            if not html: return None
            
            soup = BeautifulSoup(html, "html.parser")
            if not _page_matches_reference(soup, reference):
                return None
            
            pdf_url = _best_pdf_link(soup, url, reference)
            if pdf_url:
                return fallback_download_pdf(pdf_url, reference)
            return None
        except Exception as e:
            logger.debug(f"Web Searcher: fallback error on {url}: {e}")
            return None
    except Exception as e:
        logger.debug(f"Web Searcher: error on {url}: {e}")
        return None

    try:
        if resp.status_code != 200:
            logger.debug(f"Web Searcher: {url} returned {resp.status_code}")
            return None

        # Direct PDF response
        content_type = resp.headers.get("content-type", "").lower()
        if "application/pdf" in content_type or resp.content.startswith(b"%PDF"):
            # Still verify: check first 500 bytes of text for a keyword match
            first_text = resp.content[:2000].decode("latin-1", errors="ignore").lower()
            if _has_keyword_hit(reference, first_text):
                return _save_bytes(resp.content, url, reference)
            else:
                logger.debug(f"Web Searcher: PDF content doesn't match reference, skipping {url}")
                return None

        soup = BeautifulSoup(resp.content, "html.parser")

        # ── Page title check — skip if clearly about a different document ──────────
        if not _page_matches_reference(soup, reference):
            logger.debug(f"Web Searcher: page title mismatch, skipping {url}")
            return None

        pdf_url = _best_pdf_link(soup, url, reference)
        if pdf_url:
            return _download_pdf(session, pdf_url, reference)

    except Exception as e:
        logger.debug(f"Web Searcher: parsing error on {url}: {e}")

    return None


def _page_matches_reference(soup: BeautifulSoup, reference: str) -> bool:
    """
    Check if the visited page is actually about the reference document.
    Reads the page <title> and first <h1>/<h2> to find keyword overlap.
    Returns True if at least 1 meaningful keyword from the reference appears
    in the page heading, so we don't download a PDF from the wrong page.
    """
    # Collect page heading text
    heading_parts = []
    title_tag = soup.find("title")
    if title_tag:
        heading_parts.append(title_tag.get_text(strip=True).lower())
    for tag in soup.find_all(["h1", "h2"], limit=3):
        heading_parts.append(tag.get_text(strip=True).lower())
    page_text = " ".join(heading_parts)

    # --- REJECTION LOGIC (No Circulars/Orders/Drafts) ---
    is_regulation_req = "regulation" in reference.lower()
    is_act_req        = "act" in reference.lower()
    
    if is_regulation_req or is_act_req:
        found_junk = any(x in page_text for x in ["circular", "order", "draft", "consultation", "discussion", "settlement", "adjudication"])
        # Only allow if the reference itself mentions these keywords
        if found_junk and not any(x in reference.lower() for x in ["circular", "order", "draft"]):
            logger.debug(f"Web Searcher: rejecting page because it looks like junk (circular/draft/order) for a Regulation/Act request: {reference}")
            return False

    return _has_keyword_hit(reference, page_text)


def _has_keyword_hit(reference: str, text: str) -> bool:
    """
    Return True if the page text sufficiently matches the reference.

    Strategy:
      - For SEBI-style refs like "SEBI (Infrastructure Investment Trusts) Regulations, 2014"
        words like "Securities", "Exchange", "Board", "India" appear on EVERY SEBI page,
        so we extract the parenthesized part ("Infrastructure Investment Trusts")
        as the distinctive keywords and require >=50% of those to match.
      - For plain act refs like "Companies Act, 1956", any single keyword is enough.
    """
    stop     = {"the", "of", "to", "and", "in", "for", "a", "an", "by", "or", "as",
                "securities", "exchange", "board", "india"}   # strip SEBI boilerplate
    year_pat = re.compile(r"\d{4}")

    # Check if reference follows "... (Specific Name) Regulations/Act, YEAR" pattern
    paren_m = re.search(r"\(([^)]+)\)", reference)
    if paren_m:
        inner    = paren_m.group(1).lower()
        ref_norm = re.sub(r"[()[\],.;:\'\"\`]", " ", inner)
        keywords = list(dict.fromkeys([
            w for w in ref_norm.split()
            if len(w) > 4 and w not in stop and not year_pat.fullmatch(w)
        ]))
        if keywords:
            hits  = sum(1 for kw in keywords if kw in text)
            ratio = hits / len(keywords)
            logger.debug(
                f"Web Searcher: page check — "
                f"hits={hits}/{len(keywords)} ({ratio:.0%}) "
                f"keywords={keywords}"
            )
            return ratio >= 0.50

    # Fallback: plain act reference — any single keyword is enough
    ref_norm = re.sub(r"[()[\],.;:\'\"\`]", " ", reference.lower())
    keywords = list(dict.fromkeys([
        w for w in ref_norm.split()
        if len(w) > 4
        and w not in {"the","of","to","and","in","for","a","an","by","or","as"}
        and not year_pat.fullmatch(w)
    ]))
    if not keywords:
        return True
    return any(kw in text for kw in keywords)


def _best_pdf_link(soup: BeautifulSoup, base_url: str, reference: str) -> str | None:
    """
    Find the most relevant PDF link on a parsed page.
    Scores by: keyword match against the specific reference > generic signals.
    """
    stop     = {"the", "of", "to", "and", "in", "for", "a", "an", "by", "or", "as"}
    year_pat = re.compile(r'\d{4}')
    ref_norm = re.sub(r'[()[],.;:\'"\`]', " ", reference.lower())
    ref_keywords = list(dict.fromkeys([
        w for w in ref_norm.split()
        if len(w) > 4 and w not in stop and not year_pat.fullmatch(w)
    ]))

    candidates: list[tuple[int, str]] = []

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        full = urljoin(base_url, href)
        if not _looks_like_pdf_url(full):
            continue
        # Score: how many reference keywords appear in the link text or URL
        link_text = a.get_text(strip=True).lower()
        link_context = (link_text + " " + full.lower())
        score = sum(1 for kw in ref_keywords if kw in link_context)
        candidates.append((score, full))

    # Also check iframes (SEBI specifically embeds PDFs in iframes)
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src")
        if not src:
            continue
        full = urljoin(base_url, src)
        if _looks_like_pdf_url(full) or "file=" in full:
            # Unwrap ?file= parameter if present
            if "file=" in full:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(full).query)
                unwrapped = qs.get("file", [None])[0]
                if unwrapped: full = unwrapped
            
            # Boost score for an iframe prominently displayed
            candidates.append((10, full)) # Heavily favour the main embedded iframe

    if not candidates:
        return None

    candidates.sort(reverse=True)
    best_score, best_url = candidates[0]
    logger.debug(f"Web Searcher: best PDF link (score={best_score}): {best_url}")
    return best_url


# ===========================================================================
# Download helpers
# ===========================================================================

def _create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return session


def _download_pdf(
    session: requests.Session, pdf_url: str, reference: str
) -> dict | None:
    """Download a PDF from a URL and save to REPO_DIR."""
    try:
        logger.info(f"Web Searcher: downloading — {pdf_url}")
        resp = session.get(pdf_url, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        return _save_bytes(resp.content, pdf_url, reference)
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"Web Searcher: download failed ({e}) — trying fallback for {pdf_url}")
        try:
            from scrapers.crawl4ai_downloader import fallback_download_pdf
            return fallback_download_pdf(pdf_url, reference)
        except Exception as fallback_e:
            logger.warning(f"Web Searcher: fallback failed {pdf_url}: {fallback_e}")
            return None
    except Exception as e:
        logger.warning(f"Web Searcher: download failed {pdf_url}: {e}")
        return None


def _save_bytes(content: bytes, source_url: str, reference: str) -> dict | None:
    """Validate bytes are a PDF then write to REPO_DIR."""
    if not content.startswith(b"%PDF"):
        logger.debug(f"Web Searcher: response from {source_url} is not a PDF")
        return None
    safe   = re.sub(r'[\\/*?:"<>|]', "", reference)
    safe   = re.sub(r'\s+', "_", safe.strip())[:120]
    fname  = f"{safe}.pdf" if safe else f"fallback_{abs(hash(source_url)) % 100000}.pdf"
    fpath  = os.path.join(REPO_DIR, fname)
    with open(fpath, "wb") as f:
        f.write(content)
    logger.info(f"Web Searcher: saved → {fpath}")
    #return fpath
    return {"filepath": fpath, "source_pdf_url": source_url}


def _looks_like_pdf_url(url: str) -> bool:
    """Returns True ONLY for explicit .pdf extension URLs, SEBI attachdocs, or known safe bitstream paths."""
    lower = url.lower().split("?")[0].split("#")[0]
    return lower.endswith(".pdf") or "/bitstream/" in lower or "attachdocs" in lower or "file=" in url.lower()


def _pdf_url_matches_reference(url: str, reference: str) -> bool:
    """
    Check if a direct PDF URL's filename/slug likely refers to the right document.
    For SEBI, regulation PDF names often contain keywords (e.g. AIFregulations2012_p.pdf).
    Numeric-ID-only filenames (1512725249793.pdf) are attachments/circulars — skip them.
    """
    import re as _re
    stop = {"the","of","to","and","in","for","a","an","by","or","as",
            "securities","exchange","board","india","sebi"}
    year_pat = _re.compile(r"\d{4}")

    # Extract distinctive part from parentheses for SEBI references
    paren_m = _re.search(r"\(([^)]+)\)", reference)
    if paren_m:
        inner    = paren_m.group(1)
        ref_text = _re.sub(r"[()\[\],.;:\'\"\`]", " ", inner.lower())
    else:
        ref_text = _re.sub(r"[()\[\],.;:\'\"\`]", " ", reference.lower())

    year_m   = _re.search(r"\b(19|20)\d{2}\b", reference)
    keywords = [w for w in ref_text.split()
                if len(w) > 4 and w not in stop and not year_pat.fullmatch(w)]

    # Get the filename portion of the URL
    url_lower = url.lower().split("?")[0].split("#")[0]
    filename  = url_lower.split("/")[-1]

    # Reject numeric-ID filenames like "1512725249793.pdf" — always wrong for regulations...
    # UNLESS it is specifically located inside SEBI's `legal/regulations` or `attachdocs` path
    # and we requested a SEBI document.
    if _re.match(r"\d+(?:_\d+)?\.pdf$", filename):
        if "sebi.gov.in" not in url_lower:
            return False
        # If it's pure numbers, it better be tightly scoped to SEBI's regulation paths
        if "/legal/regulations/" not in url_lower and "/attachdocs/" not in url_lower and "/commondocs/" not in url_lower:
             return False

    # --- REJECTION LOGIC (No Circulars/Orders/Drafts in URL or filename) ---
    is_regulation_req = "regulation" in reference.lower()
    is_act_req        = "act" in reference.lower()
    
    if is_regulation_req or is_act_req:
        found_junk = any(x in url_lower for x in ["circular", "order", "draft", "consultation", "discussion", "settlement", "adjudication"])
        if found_junk and not any(x in reference.lower() for x in ["circular", "order", "draft"]):
            return False

    # Slugify the full URL path for keyword matching
    url_slug = _re.sub(r"[/_-]", " ", url_lower)

    if not keywords:
        # No distinctive keywords — fall back to year + "regulations" in URL
        if bool(year_m and year_m.group(0) in url_slug and "regulation" in url_slug):
            return True
        # Or abbreviated SEBI regulations/acts
        return bool("reg" in filename or "act" in filename)

    # At least 1 distinctive keyword must appear in the URL
    if any(kw in url_slug for kw in keywords):
        return True

    # Fallback 1: year + "regulations" both in URL (covers abbreviations like AIFregulations2012)
    if bool(year_m and year_m.group(0) in url_slug and "regulation" in url_slug):
        return True

    # Fallback 2: filename contains "reg" or "act" (covers tgt abbreviations like dtreg, act05a, pfutpregu)
    # Since we already rejected purely numeric attachments, any DDG-ranked PDF with
    # "reg" or "act" in the name for a Regulation/Act query is highly likely to be correct.
    return bool("reg" in filename or "act" in filename)