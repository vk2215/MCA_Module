"""
MCA Reference Extraction Pipeline
===================================
Flow per input PDF:
  STEP-01  Validate the input PDF exists
  STEP-02  Extract full text from the PDF
  STEP-03  Identify regulation references via single LLM call
           ↳ Skipped if STEP-01_reference_extraction.json already exists
  STEP-04  Save the reference mapping as JSON  (STEP-01_reference_extraction.json)
  STEP-05  Download source PDFs for each reference via source router
"""

import os
import sys
import json
import logging
import re
import hashlib
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

# ── MongoDB connection (shared within this module) ────────────────────────────
MONGO_URI = os.getenv("MONGO_URI")
_mongo_client = None

def _get_db():
    """Return the compliance_db database handle (lazy singleton)."""
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    return _mongo_client["compliance_db"]

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
DATA_DIR   = "data"
OUTPUT_DIR = "output"
REPO_DIR   = "repository"

# Fixed filename for the reference extraction output — enables cache-skip
EXTRACTION_JSON = os.path.join(OUTPUT_DIR, "STEP-01_reference_extraction.json")

# ---------------------------------------------------------------------------
# Logger — configured once; all agents share the same named logger
# ---------------------------------------------------------------------------
def _setup_logger(name: str = "ReferenceExtraction") -> logging.Logger:
    """Configure and return the application logger."""
    log = logging.getLogger(name)
    log.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    log.addHandler(console_handler)

    # File handler
    Path("logs").mkdir(parents=True, exist_ok=True)
    log_file = f"logs/reference_extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    try:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        log.addHandler(file_handler)
    except Exception:
        print(f"Warning: Could not create log file at {log_file}")

    return log


logger = _setup_logger()

# ---------------------------------------------------------------------------
# Agent / scraper imports (after logger is defined so sub-modules can use it)
# ---------------------------------------------------------------------------
from agents.pdf_extractor  import extract_text_from_pdf
from agents.llm_handler    import LLMHandler
from scrapers.source_router import download_reference_pdf


# ===========================================================================
# Pipeline steps
# ===========================================================================

def load_cached_extraction() -> dict | None:
    """
    Return the previously saved reference extraction JSON if it exists,
    otherwise return None (caller should run the LLM step).
    """
    if os.path.exists(EXTRACTION_JSON):
        with open(EXTRACTION_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Cache hit — loaded existing extraction from: {EXTRACTION_JSON}")
        return data
    return None


def process_pdf(pdf_filename: str, llm: LLMHandler) -> dict:
    """
    STEP-01 → STEP-04: Extract text from PDF, identify references via LLM,
    and build the reference mapping dict.
    """
    logger.info(f"\nProcessing PDF: {pdf_filename}")
    logger.info("-" * 60)

    # ── STEP-01  Validate input PDF exists ───────────────────────────────────
    logger.info("STEP-01  Validating input PDF path")
    pdf_path = os.path.join(DATA_DIR, pdf_filename)
    if not os.path.exists(pdf_path):
        logger.error(f"PDF not found: {pdf_path}")
        return None

    # ── STEP-02  Extract full text from input PDF ────────────────────────────
    logger.info("STEP-02  Extracting text from input PDF")
    extracted = extract_text_from_pdf(pdf_path)
    logger.info(f"Extracted {len(extracted['full_text'])} chars from {extracted['pages']} pages")

    # ── STEP-03  Identify regulation references via single LLM call ──────────
    logger.info("STEP-03  Identifying regulation references via LLM")
    references = llm.extract_references(extracted["full_text"])

    if not references:
        logger.warning("No references found in document")

    logger.info(f"Found {len(references)} references")
    for idx, ref in enumerate(references, 1):
        sub = f" → {ref['sub_reference']}" if ref.get("sub_reference") else ""
        logger.info(f"  [{idx}] {ref['reference']}{sub}")

    # ── STEP-04  Build and return the final reference mapping ─────────────────
    logger.info("STEP-04  Building final reference mapping")
    return {
        "source_pdf":       pdf_filename,
        "extraction_date":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_references": len(references),
        "references":       references,
    }


def download_source_pdfs(reference_mapping: dict) -> dict:
    """
    STEP-05: For each reference in the mapping, route to the correct scraper
    by the `source` field and download the matching PDF to REPO_DIR.

    Updates each reference dict in-place with:
      - `pdf_path`       → local filepath string if download succeeded, else None
      - `source_pdf_url` → the URL the PDF was scraped from, else "" (cache hit
                           with no stored URL) or None (download failed)

    Returns the updated mapping.
    """
    references = reference_mapping.get("references", [])
    logger.info(f"STEP-05  Downloading source PDFs for {len(references)} references")

    for idx, ref in enumerate(references, 1):
        reference = ref.get("reference", "")
        source    = ref.get("source", "")
        logger.info(f"  [{idx}/{len(references)}] {reference}  (source: {source or 'unknown'})")

        try:
            result = download_reference_pdf(reference, source)
        except Exception as e:
            logger.warning(f"    ✗ Scraper error for '{reference}': {e}")
            result = None

        # ── Unpack the dict returned by the router ────────────────────────────
        if result:
            ref["pdf_path"]       = result["filepath"]
            ref["source_pdf_url"] = result["source_pdf_url"]   # "" if local cache hit
            logger.info(f"    ✓ Saved : {result['filepath']}")
            if result["source_pdf_url"]:
                logger.info(f"    ✓ URL   : {result['source_pdf_url']}")
            else:
                logger.info(f"    ✓ URL   : (local cache — URL not stored at download time)")
        else:
            ref["pdf_path"]       = None
            ref["source_pdf_url"] = None
            logger.warning(f"    ✗ Not found: {reference}")

    return reference_mapping


# ===========================================================================
# Entry point
# ===========================================================================

def main():
    """
    Main entry point — thin runner, zero business logic.
    STEP-01  Ensure output directories exist
    STEP-02  Initialise LLM client
    STEP-03  Discover input PDFs
    STEP-04  Run reference extraction (or load from cache)
    STEP-05  Download source PDFs via source router
    """
    try:
        # ── STEP-01  Ensure output directories exist ─────────────────────────
        logger.info("STEP-01  Ensuring output directories exist")
        for directory in [DATA_DIR, OUTPUT_DIR, REPO_DIR]:
            Path(directory).mkdir(parents=True, exist_ok=True)
        logger.info(f"Directories ready: {DATA_DIR}, {OUTPUT_DIR}, {REPO_DIR}")

        logger.info("=" * 60)
        logger.info("Reference Extraction System — Starting")
        logger.info("=" * 60)

        # ── STEP-02  Check for cached reference extraction ───────────────────
        logger.info("STEP-02  Checking for cached reference extraction JSON")
        reference_mapping = load_cached_extraction()

        if reference_mapping:
            logger.info("STEP-02  Cache found — skipping LLM extraction")
        else:
            # ── STEP-03  Initialise LLM + discover PDFs + extract references ─
            logger.info("STEP-03  No cache — initialising LLMHandler")
            llm = LLMHandler()

            logger.info("STEP-03  Discovering input PDFs")
            input_pdfs = [f for f in os.listdir(DATA_DIR) if f.endswith(".pdf")]
            logger.info(f"Found {len(input_pdfs)} PDF(s) in {DATA_DIR}/")

            if not input_pdfs:
                logger.error(f"No PDF files found in {DATA_DIR}/ — nothing to process")
                return

            # Process the first PDF (one input PDF at a time)
            pdf_file = input_pdfs[0]
            if len(input_pdfs) > 1:
                logger.warning(f"Multiple PDFs found — processing only: {pdf_file}")

            reference_mapping = process_pdf(pdf_file, llm)
            if not reference_mapping:
                logger.error(f"Reference extraction failed for: {pdf_file}")
                return

            with open(EXTRACTION_JSON, "w", encoding="utf-8") as f:
                json.dump(reference_mapping, f, indent=2, ensure_ascii=False)

            logger.info("\n" + "=" * 60)
            logger.info("STEP-03 Complete — Reference Extraction Done")
            logger.info(f"Total References : {reference_mapping['total_references']}")
            logger.info(f"Saved to         : {EXTRACTION_JSON}")
            logger.info("=" * 60)

        # ── STEP-04/05  Download source PDFs via source router ─────────────────
        logger.info("STEP-04/05 Routing each reference to its source scraper for PDF download")
        reference_mapping = download_source_pdfs(reference_mapping)
        
        # Save the updated mapping (with pdf_path + source_pdf_url annotations) back to disk
        with open(EXTRACTION_JSON, "w", encoding="utf-8") as f:
            json.dump(reference_mapping, f, indent=2, ensure_ascii=False)

        
        # ── STEP-06  Extract specific reference details from downloaded PDFs ─
        logger.info("STEP-06  Extracting specific reference details from downloaded PDFs")
        DETAIL_JSON = os.path.join(OUTPUT_DIR, "STEP-02_reference_details.json")
        from agents.pdf_extractor import extract_reference_details_from_pdf
        
        # Ensure LLM is initialized
        if 'llm' not in locals():
            llm = LLMHandler()

        details_results = []
        for idx, ref in enumerate(reference_mapping.get("references", []), 1):
            pdf_path_str    = ref.get("pdf_path")
            source_pdf_url  = ref.get("source_pdf_url")   # ← NEW: carry the URL through

            if not pdf_path_str:
                logger.warning(f"  [{idx}/{len(reference_mapping['references'])}] Skipping {ref['reference']} — No PDF available")
                res = ref.copy()
                res["extracted_details"] = {
                    "extracted_definition": None,
                    "confidence":           "Low",
                    "reasoning":            "No PDF available",
                }
                details_results.append(res)
                continue
                
            # --- START EXPLODING MULTIPLE REFERENCES ---
            sentence = ref.get("sentence")
            
            # Extract exploded lists
            paths = [p.strip() for p in pdf_path_str.split("|||") if p.strip()]

            # ── Explode source_pdf_url in parallel with paths ─────────────────
            # source_pdf_url is a single URL (or "" for cache hits) — replicate
            # it across all exploded paths so every sub-result carries it.
            if source_pdf_url and "|||" in source_pdf_url:
                source_pdf_urls = [u.strip() for u in source_pdf_url.split("|||")]
            else:
                source_pdf_urls = [source_pdf_url or ""] * len(paths)

            ref_str = ref.get("reference") or ""
            if "|||" in ref_str:
                refs_list = [s.strip() for s in ref_str.split("|||")]
            else:
                refs_list = [ref_str] * len(paths)
                
            sub_ref_str = ref.get("sub_reference") or ""
            if "|||" in sub_ref_str:
                sub_refs = [s.strip() for s in sub_ref_str.split("|||")]
            else:
                sub_refs = [sub_ref_str] * len(paths)
                
            source_str = ref.get("source") or ""
            if "|||" in source_str:
                sources = [s.strip() for s in source_str.split("|||")]
            else:
                sources = [source_str] * len(paths)

            if len(paths) > 1:
                logger.info(f"  [{idx}/{len(reference_mapping['references'])}] Processing {len(paths)} documents for combined reference: {ref_str}")
            else:
                logger.info(f"  [{idx}/{len(reference_mapping['references'])}] Processing document: {ref_str}")
                
            for p_idx, path in enumerate(paths):
                # Ensure index bounds
                sr          = sub_refs[p_idx]       if p_idx < len(sub_refs)       else (sub_refs[-1]       if sub_refs       else None)
                cur_ref     = refs_list[p_idx]       if p_idx < len(refs_list)      else (refs_list[-1]      if refs_list      else "")
                cur_source  = sources[p_idx]         if p_idx < len(sources)        else (sources[-1]        if sources        else None)
                cur_pdf_url = source_pdf_urls[p_idx] if p_idx < len(source_pdf_urls) else (source_pdf_urls[-1] if source_pdf_urls else "")
                
                logger.info(f"    -> Extracting from: {path} (target: {sr or 'main'}) for: {cur_ref}")
                detail = extract_reference_details_from_pdf(path, sr, sentence, llm)
                
                # --- SELF-HEALING RETRY ---
                if not detail.get("extracted_definition") and "JSON decode error" in str(detail.get("reasoning", "")):
                    logger.warning(f"    ! Extraction failed for {cur_ref} due to parsing error. Retrying with high-effort mode...")
                    detail = extract_reference_details_from_pdf(path, sr, sentence, llm)
                # -------------------------
                
                new_res = {
                    "reference":      cur_ref,
                    "sub_reference":  sr,
                    "sentence":       sentence,
                    "source":         cur_source,
                    "pdf_path":       path,
                    "source_pdf_url": cur_pdf_url,
                    "extracted_details": {
                        "extracted_definition": detail.get("extracted_definition"),
                        "meaningful_context":   detail.get("meaningful_context", "Meaningful context not available."),
                        "confidence":           detail.get("confidence", "Low"),
                        "reasoning":            detail.get("reasoning", "No details extracted"),
                        "location_metadata":    detail.get("location_metadata", {}),
                        "source_url":           detail.get("source_url")
                    }
                }
                details_results.append(new_res)
            
            # Save progressively so user can see results in real-time
            # Deduplicate by (reference, sub_reference) — keep FIRST occurrence only
            seen_keys = set()
            deduped_results = []
            for r in details_results:
                key = (
                    r.get("reference", "").strip().lower(), 
                    (r.get("sub_reference") or "").strip().lower(),
                    (r.get("sentence") or "").strip()
                )
                if key not in seen_keys:
                    seen_keys.add(key)
                    deduped_results.append(r)

            with open(DETAIL_JSON, "w", encoding="utf-8") as f:
                json.dump(deduped_results, f, indent=2, ensure_ascii=False)
            
        # Final deduplication before MongoDB save
        seen_keys = set()
        deduped_results = []
        for r in details_results:
            key = (
                r.get("reference", "").strip().lower(), 
                (r.get("sub_reference") or "").strip().lower(),
                (r.get("sentence") or "").strip()
            )
            if key not in seen_keys:
                seen_keys.add(key)
                deduped_results.append(r)

        with open(DETAIL_JSON, "w", encoding="utf-8") as f:
            json.dump(deduped_results, f, indent=2, ensure_ascii=False)

        logger.info(f"STEP-06 Complete — {len(deduped_results)} unique references saved to {DETAIL_JSON} (from {len(details_results)} total)")

        # ── STEP-07  Persist reference details to MongoDB ──────────────────────
        logger.info("STEP-07  Saving reference details to MongoDB (reference_details collection)")
        saved_count = save_references_to_mongo(details_results)
        logger.info(f"STEP-07 Complete — {saved_count} records upserted into MongoDB")

        logger.info("\n" + "=" * 60)
        logger.info("Pipeline Complete!")
        downloaded = sum(1 for r in reference_mapping["references"] if r.get("pdf_path"))
        logger.info(f"  References     : {reference_mapping['total_references']}")
        logger.info(f"  PDFs downloaded: {downloaded}")
        logger.info(f"  Output JSON    : {EXTRACTION_JSON}")
        logger.info(f"  MongoDB records: {saved_count}")
        logger.info("=" * 60)

    except Exception as e:
        logger.critical(f"Critical error: {e}")
        sys.exit(1)


# ===========================================================================
# MongoDB helpers
# ===========================================================================

def save_references_to_mongo(details_results: list) -> int:
    """
    Upsert each reference detail record from STEP-02 into the
    `reference_details` MongoDB collection.

    _id strategy: slugified reference field (handles ||| multi-refs by
    joining with '__').
    Returns the number of documents upserted/updated.
    """
    try:
        db = _get_db()
        coll = db["reference_details"]
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        return 0

    # Clear previous data so every run is a clean slate
    deleted = coll.delete_many({})
    logger.info(f"  Cleared {deleted.deleted_count} old records from reference_details")

    count = 0
    for record in details_results:
        ref_text     = record.get("reference", "") or ""
        sentence     = record.get("sentence", "") or ""
        # Build _id based on reference name + sentence string (via md5)
        hash_input = f"{ref_text}_{sentence}".encode('utf-8')
        doc_id = hashlib.md5(hash_input).hexdigest()
        
        if not ref_text.strip():
            continue

        doc = {
            "_id":              doc_id,
            "reference":        ref_text,
            "sub_reference":    (record.get("sub_reference") or "").strip() or None,
            "sentence":         record.get("sentence"),
            "source":           record.get("source"),
            "pdf_path":         record.get("pdf_path"),
            "source_pdf_url":   record.get("source_pdf_url") or None,
            "extracted_details": record.get("extracted_details", {}),
        }

        try:
            coll.update_one({"_id": doc_id}, {"$set": doc}, upsert=True)
            count += 1
        except Exception as e:
            logger.warning(f"Failed to upsert record '{doc_id}': {e}")

    logger.info(f"  Upserted {count} records into reference_details")
    return count


if __name__ == "__main__":
    main()