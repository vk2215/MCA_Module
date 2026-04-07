import os
import re
import logging
import asyncio
from pathlib import Path

logger = logging.getLogger("ReferenceExtraction")

REPO_DIR = "repository"

async def _download_pdf_with_playwright(url: str, filepath: str) -> bool:
    from playwright.async_api import async_playwright
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                accept_downloads=True
            )
            page = await context.new_page()
            
            # Use request interception to save the PDF if navigating directly to it
            # Playwright handles downloads differently if it's a direct PDF URL vs an attachment
            try:
                # Setup download handler (for attachments)
                async with page.expect_download(timeout=15000) as download_info:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                download = await download_info.value
                await download.save_as(filepath)
                await browser.close()
                return True
                
            except TimeoutError:
                # If it didn't trigger a download, it might be rendered in the browser natively (PDF viewer)
                # Let's get the buffer directly
                pass
            except Exception as e:
                logger.debug(f"Crawl4AI/Playwright Fallback: expect_download error (trying alternative): {e}")
                
            # Direct buffer extraction if not triggered as attachment
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if resp:
                content_type = resp.headers.get("content-type", "").lower()
                if "pdf" in content_type:
                    buffer = await resp.body()
                    if buffer.startswith(b"%PDF"):
                        with open(filepath, "wb") as f:
                            f.write(buffer)
                        await browser.close()
                        return True
            
            await browser.close()
            return False
            
    except Exception as e:
        logger.error(f"Crawl4AI/Playwright Fallback: Failed to download PDF {url}: {e}")
        return False

async def _get_page_content_with_crawl4ai(url: str) -> str | None:
    try:
        from crawl4ai import AsyncWebCrawler
        async with AsyncWebCrawler(verbose=True) as crawler:
            result = await crawler.arun(url=url)
            return result.html
    except ImportError:
        logger.error("crawl4ai not installed.")
        return None
    except Exception as e:
        logger.error(f"Crawl4AI Fallback: Failed to get page {url}: {e}")
        return None

def fallback_download_pdf(url: str, reference: str, title_text: str = None) -> dict | None:
    """
    Synchronous wrapper for downloading a PDF via headless browser.
    
    Returns: {"filepath": str, "source_pdf_url": str} or None if failed.
    """
    Path(REPO_DIR).mkdir(parents=True, exist_ok=True)

    ref_text = title_text or reference
    safe_title = re.sub(r'[\\/*?:"<>|]', "", ref_text)
    safe_title = re.sub(r'\s+', "_", safe_title.strip())[:120]
    filename   = f"{safe_title}.pdf" if safe_title else f"fallback_c4ai_{hash(url) % 100000}.pdf"
    filepath   = os.path.join(REPO_DIR, filename)

    logger.info(f"Crawl4AI Fallback: Attempting headless download from {url}")
    
    try:
        # Check if running in an existing event loop
        loop = asyncio.get_running_loop()
        # If we are in an event loop, we have to run it as a task or synchronous run
        try:
            import nest_asyncio
            nest_asyncio.apply()
        except ImportError:
            pass
        success = asyncio.run(_download_pdf_with_playwright(url, filepath))
    except RuntimeError:
        success = asyncio.run(_download_pdf_with_playwright(url, filepath))
        
    if success:
        logger.info(f"Crawl4AI Fallback: saved → {filepath}")
        # Your current code already does this correctly:
        return {"filepath": filepath, "source_pdf_url": url}
    
    return None

def fallback_get_html(url: str) -> str | None:
    """Synchronous wrapper to get HTML of a page via crawl4ai headless browser."""
    logger.info(f"Crawl4AI Fallback: Fetching HTML for {url}")
    try:
        loop = asyncio.get_running_loop()
        try:
            import nest_asyncio
            nest_asyncio.apply()
        except ImportError:
            pass
        html = asyncio.run(_get_page_content_with_crawl4ai(url))
    except RuntimeError:
        html = asyncio.run(_get_page_content_with_crawl4ai(url))
        
    return html