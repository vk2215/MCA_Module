import os
import re
import logging
import requests
import asyncio
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup

logger = logging.getLogger("ReferenceExtraction")

# Constants
SEBI_BASE_URL  = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListingAll=yes"
SEBI_AJAX_URL  = "https://www.sebi.gov.in/sebiweb/ajax/home/getnewslistallinfo.jsp"
REPO_DIR       = "repository"
MAX_PAGES      = 10   # pagination guard when searching

# Public API
def search_and_download_sebi_pdf(reference: str) -> dict | None:
    """
    Search SEBI's paginated listing for a document whose title matches
    `reference`, download the first matching PDF, and save it to REPO_DIR.
    
    Returns: {"filepath": str, "source_pdf_url": str} or None
    """
    logger.info(f"SEBI Scraper: searching for — {reference}")

    # Ensure repository directory exists
    Path(REPO_DIR).mkdir(parents=True, exist_ok=True)

    session = _create_session()

    normalized_reference = _normalize_title(reference)
    year_match  = re.search(r'\b(19|20)\d{2}\b', reference)
    target_year = int(year_match.group(0)) if year_match else None
    
    # Generate search text
    all_keywords = _extract_keywords(reference)
    if len(all_keywords) < 3:
        raw_words = [w.strip('()[].,;:') for w in normalized_reference.split() if len(w.strip('()[].,;:')) >= 3]
        search_keywords = raw_words
    else:
        search_keywords = all_keywords

    search_text = " ".join(search_keywords[:8])
    updated_search_text = f"\"{reference}\" Last Amended 2024" if "Regulation" in reference else f"\"{reference}\" consolidated"
    
    logger.info(f"SEBI Scraper: searching with keywords — {search_text!r}")

    # --- Pass 1: AJAX Search (fast, but often blocked) ---
    try:
        results = _run_ajax_search(session, search_text, target_year, "search")
        if results:
            for title, url, date_text in results:
                if _is_title_match(reference, title, target_year, date_text):
                    logger.info(f"SEBI Scraper: matched title — '{title}'")
                    return _download_link(session, url, reference, title)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        logger.warning(f"SEBI Scraper: AJAX Search failed (connection/timeout): {e}")
    except Exception as e:
        logger.debug(f"SEBI Scraper: AJAX Search unexpected error: {e}")

    # --- Pass 2: Browser-Based Search (Fallback for blocks/failures) ---
    logger.info("SEBI Scraper: trying browser-based search (Playwright)")
    try:
        results = _search_sebi_with_browser(search_text, target_year)
        if results:
            for title, url, date_text in results:
                if _is_title_match(reference, title, target_year, date_text):
                    logger.info(f"SEBI Scraper: matched title (browser) — '{title}'")
                    return _download_link(session, url, reference, title)
    except Exception as e:
        logger.error(f"SEBI Scraper: Browser search failed: {e}")

    # --- Pass 3: Date-range Browse (if search yielded nothing) ---
    if target_year:
        logger.info(f"SEBI Scraper: final fallback — trying date-range browse for {target_year}")
        try:
            results = _run_ajax_search(session, "", target_year, "browse")
            if results:
                for title, url, date_text in results:
                    if _is_title_match(reference, title, target_year, date_text):
                        logger.info(f"SEBI Scraper: matched title (browse) — '{title}'")
                        return _download_link(session, url, reference, title)
        except Exception as e:
            logger.debug(f"SEBI Scraper: AJAX Browse failed: {e}")

    # --- Pass 4: Updated/Amended Search (Primary for CDMDF and New Clauses) ---
    logger.info(f"SEBI Scraper: searching for latest UPDATED version — {updated_search_text!r}")
    try:
        results = _run_ajax_search(session, updated_search_text, None, "search") 
        if results:
            for title, url, date_text in results:
                # Use a looser title match for updated regs (year might be different)
                if _is_title_match(reference, title, None, date_text):
                    logger.info(f"SEBI Scraper: found updated/amended version — '{title}'")
                    return _download_link(session, url, reference, title)
    except Exception as e:
        logger.debug(f"SEBI Scraper: Updated Search pass failed: {e}")

    logger.warning(f"SEBI Scraper: no matching PDF found for — {reference}")
    return None

def _run_ajax_search(session, search_text, target_year, search_pass):
    """Helper to run the AJAX POST search/browse."""
    results = []
    for page_number in range(2):  # check first 2 pages
        try:
            if search_pass == "search":
                post_data = {
                    "nextValue": str(page_number + 1),
                    "next":      "s",          # 's' for search
                    "search":    search_text,  # the actual query string
                    "fromDate":  str(target_year - 1) + "-01-01" if target_year else "",
                    "toDate":    str(target_year + 1) + "-12-31" if target_year else "",
                    "deptId":    "-1",
                   "sid":       "-1",
                    "ssid":      "-1",
                    "smid":      "-1",
                    "cid":       "-1",
                    "sText":     "-- All Section --",
                    "ssText":    "-- All Sub Section --",
                    "smText":    "-- All Sub Section List --",
                    "cText":     "-- All Info for --",
                    "doDirect":  "-1",
                }
            else:
                # Browse all docs in target year range
                post_data = {
                    "nextValue": str(page_number + 1),
                    "next":      "n",          # 'n' for browse/next
                    "search":    "n",
                    "fromDate":  str(target_year) + "-01-01" if target_year else "",
                    "toDate":    str(target_year) + "-12-31" if target_year else "",
                    "deptId":    "-1",
                    "sid":       "-1",
                    "ssid":      "-1",
                    "smid":      "-1",
                    "cid":       "-1",
                    "sText":     "-- All Section --",
                    "ssText":    "-- All Sub Section --",
                    "smText":    "-- All Sub Section List --",
                    "cText":     "-- All Info for --",
                    "doDirect":  str(page_number),
                }

            resp = session.post(SEBI_AJAX_URL, data=post_data, timeout=20)
            if resp.status_code != 200:
                break

            soup  = BeautifulSoup(resp.content, "html.parser")
            table = soup.find("table", {"id": "sample_1"})
            if not table:
                snippet = resp.text.strip()[:1000]
                logger.debug(f"SEBI Scraper: [{search_pass}] no listing table. Snippet: {snippet}")
                break

            rows = table.find_all("tr")[1:]   # skip header row
            if not rows:
                break

            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 3: continue
                date_text = cols[0].get_text(strip=True)
                title_cell = cols[2]
                a_tag = title_cell.find("a")
                if not a_tag: continue
                
                title = a_tag.get_text(strip=True)
                link  = a_tag["href"]
                results.append((title, link, date_text))
            
            # Check for pagination
            total_page_input = soup.find("input", {"name": "totalpage"})
            if total_page_input:
                try:
                    if page_number + 1 >= int(total_page_input.get("value", "0")):
                        break
                except ValueError:
                    break
            else:
                break
        except Exception as e:
            logger.debug(f"SEBI Scraper: [{search_pass}] AJAX iteration failed: {e}")
            break
            
    return results

def _search_sebi_with_browser(search_text, target_year):
    """Synchronous entry point for browser-based search."""
    try:
        try:
            import nest_asyncio
            nest_asyncio.apply()
        except ImportError:
            pass
        # Use a fresh event loop if needed
        return asyncio.run(_search_sebi_playwright(search_text, target_year))
    except Exception as e:
        logger.error(f"SEBI Scraper: Browser search failed: {e}")
        return []

async def _search_sebi_playwright(search_text, target_year):
    from playwright.async_api import async_playwright
    results = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(SEBI_BASE_URL, wait_until="domcontentloaded", timeout=60000)
            
            # Wait for and fill search
            await page.wait_for_selector("input[name='search']", timeout=10000)
            await page.fill("input[name='search']", search_text)
            
            # Click GO
            await page.click("input.go-btn", timeout=5000)
            
            # Wait for table
            try:
                await page.wait_for_selector("#sample_1", timeout=15000)
                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                table = soup.find("table", {"id": "sample_1"})
                if table:
                    rows = table.find_all("tr")[1:]
                    for row in rows:
                        cols = row.find_all("td")
                        if len(cols) < 3: continue
                        date_text = cols[0].get_text(strip=True)
                        a_tag = cols[2].find("a")
                        if a_tag:
                            results.append((a_tag.get_text(strip=True), a_tag["href"], date_text))
            except Exception as e:
                logger.debug(f"SEBI Scraper: Playwright results not found/timed out: {e}")
            
            await browser.close()
    except Exception as e:
        logger.error(f"SEBI Scraper: Playwright sub-process failure: {e}")
    return results

'''
def _download_link(session, link, reference, title_text):
    """Helper to resolve and download a PDF from a listing link."""
    pdf_url = _resolve_pdf_url(session, link)
    if not pdf_url:
        logger.warning(f"SEBI Scraper: could not resolve PDF URL for — {link}")
        return None

    local_path = _download_pdf(session, pdf_url, title_text)
    if local_path:
        logger.info(f"SEBI Scraper: successfully saved PDF — {local_path}")
        #return local_path
        return {"filepath": local_path, "source_pdf_url": pdf_url}
    return None
'''

def _download_link(session, link, reference, title_text):
    """Helper to resolve and download a PDF from a listing link."""
    pdf_url = _resolve_pdf_url(session, link)
    if not pdf_url:
        logger.warning(f"SEBI Scraper: could not resolve PDF URL for — {link}")
        return None

    local_path = _download_pdf(session, pdf_url, title_text)
    if local_path:
        logger.info(f"SEBI Scraper: successfully saved PDF — {local_path}")
        # Return metadata dictionary for hyperlink support
        return {
            "filepath": local_path, 
            "source_pdf_url": pdf_url
        }
    return None

def _create_session() -> requests.Session:
    """Create a pre-configured requests session for SEBI."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept":   "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer":  SEBI_BASE_URL,
    })
    return session

def _extract_keywords(reference: str) -> list[str]:
    phrase = re.sub(r'\s*\(\d+\s+of\s+\d+\)', '', reference)
    # Allow years in the search query to help retrieve specific notifications/regulations
    fillers = r'\b(chapter|schedule|section|clause|sub|regulation|of|the|and|in|for|to|a|an)\b'
    phrase = re.sub(fillers, '', phrase, flags=re.IGNORECASE)
    common_sebi_terms = r'\b(securities|exchange|board|india|sebi)\b'
    words = [w.strip('()[].,;:') for w in phrase.split() if w.strip('()[].,;:')]
    filtered = [w for w in words if len(w) >= 3]
    if len(filtered) < 3:
        return filtered
    unique_keywords = [w for w in filtered if not re.match(common_sebi_terms, w, re.I)]
    return unique_keywords if unique_keywords else filtered

def _normalize_title(text: str) -> str:
    normalized = (text or "").lower()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[()[\],.;:'\"`]", " ", normalized)
    normalized = re.sub(r'\s+', " ", normalized).strip()
    return normalized

def _is_title_match(reference, page_title, target_year, date_text):
    ref_norm   = _normalize_title(reference)
    title_norm = _normalize_title(page_title)
    long_form = "securities and exchange board of india"
    if long_form in ref_norm:
        ref_norm_alias = ref_norm.replace(long_form, "sebi")
    elif "sebi" in ref_norm:
        ref_norm_alias = ref_norm.replace("sebi", long_form)
    else:
        ref_norm_alias = ref_norm

    is_strong_match = (
        ref_norm in title_norm or 
        title_norm in ref_norm or 
        ref_norm_alias in title_norm or 
        title_norm in ref_norm_alias
    )

    # --- REJECTION LOGIC ---
    # If the user asks for a "Regulation" or "Act", don't return a "Circular", "Order" or "Draft"
    # unless the reference specifically mentions them. This prevents picking up circulars 
    # instead of the core law files.
    is_regulation_req = "regulation" in ref_norm
    is_act_req        = "act" in ref_norm
    
    found_circular = "circular" in title_norm or "master circular" in title_norm or "circulars" in title_norm or " cir " in f" {title_norm} " or " cir/" in title_norm
    found_order    = "order" in title_norm or "settlement" in title_norm or "adjudication" in title_norm
    found_draft    = "draft" in title_norm or "consultation" in title_norm or "discussion paper" in title_norm
    
    if (is_regulation_req or is_act_req):
        if (found_circular or found_order or found_draft):
            # Only allow if the reference text itself has these words
            if "circular" not in ref_norm and "order" not in ref_norm and "draft" not in ref_norm:
                return False 
    # -----------------------

    if is_strong_match:
        # Check Year conflict in strong match
        if target_year:
            year_match = re.search(r'\b(19|20)\d{2}\b', title_norm + " " + date_text)
            if year_match:
                # If both have years, they must be close (+/- 1)
                # This prevents matching "2026 Regulations" with "2008 Notifications"
                if abs(int(year_match.group(0)) - target_year) <= 1:
                    return True
                else:
                    return False # Active conflict
            else:
                # No year found in document title/date, assume it's the consolidated master
                return True
        return True

    keywords = _extract_keywords(reference)
    if not keywords: return is_strong_match
    
    title_lower = page_title.lower()
    hits = sum(1 for kw in keywords if kw.lower() in title_lower)
    min_hits = max(1, len(keywords) // 2)
    
    if hits >= min_hits:
        if target_year:
            year_match = re.search(r'\b(19|20)\d{2}\b', title_norm + " " + date_text)
            if year_match:
                if abs(int(year_match.group(0)) - target_year) <= 1:
                    return True
            elif hits == len(keywords):
                # All keywords match and no conflicting year found - accept
                return True
        else:
            return True
            
    return False

def _resolve_pdf_url(session, link):
    if not link: return None
    full_link = urljoin(SEBI_BASE_URL, link)
    if full_link.lower().endswith(".pdf") or "attachdocs" in full_link.lower(): return full_link
    unwrapped = _unwrap_file_param(full_link)
    if unwrapped: return unwrapped
    try:
        resp = session.get(full_link, timeout=15)
        soup = BeautifulSoup(resp.content, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            full_href = urljoin(full_link, href)
            if full_href.lower().endswith(".pdf") or "attachdocs" in full_href.lower(): return full_href
        iframe = soup.find("iframe")
        if iframe and iframe.get("src"):
            iframe_url = urljoin(full_link, iframe["src"])
            if iframe_url.lower().endswith(".pdf") or "attachdocs" in iframe_url.lower(): return iframe_url
    except: pass
    return None

def _unwrap_file_param(url: str) -> str | None:
    if "file=" not in url: return None
    qs = parse_qs(urlparse(url).query)
    candidate = qs.get("file", [None])[0]
    if candidate and candidate.strip().lower().endswith(".pdf"): return candidate.strip()
    return None

def _download_pdf(session, pdf_url, title_text):
    try:
        resp = session.get(pdf_url, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        if not (resp.content.startswith(b"%PDF") or "pdf" in resp.headers.get("content-type", "").lower()): return None
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title_text)
        safe_title = re.sub(r'\s+', "_", safe_title.strip())[:120]
        filename   = f"{safe_title}.pdf" if safe_title else f"sebi_{hash(pdf_url) % 100000}.pdf"
        filepath   = os.path.join(REPO_DIR, filename)
        with open(filepath, "wb") as f: f.write(resp.content)
        return filepath
    except requests.exceptions.ConnectionError:
        try:
            from scrapers.crawl4ai_downloader import fallback_download_pdf
            return fallback_download_pdf(pdf_url, title_text, title_text)
        except: return None
    except: return None