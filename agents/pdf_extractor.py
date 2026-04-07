import logging
import pdfplumber
import re

logger = logging.getLogger("ReferenceExtraction")


def remove_hindi_text(text):
    """Remove Hindi and other non-English Unicode characters, keep only English."""
    if not text:
        return text
    
    # Remove Hindi Unicode range (U+0900 to U+097F)
    # Also remove other Indic scripts to be safe
    # Keep: ASCII (0-127) + Latin Extended (128-383) + common punctuation/symbols
    cleaned = re.sub(r'[\u0900-\u097F]', '', text)  # Hindi
    cleaned = re.sub(r'[\u0980-\u09FF]', '', cleaned)  # Bengali
    cleaned = re.sub(r'[\u0A00-\u0A7F]', '', cleaned)  # Punjabi
    cleaned = re.sub(r'[\u0A80-\u0AFF]', '', cleaned)  # Gujarati
    cleaned = re.sub(r'[\u0B00-\u0B7F]', '', cleaned)  # Oriya
    cleaned = re.sub(r'[\u0B80-\u0BFF]', '', cleaned)  # Tamil
    cleaned = re.sub(r'[\u0C00-\u0C7F]', '', cleaned)  # Telugu
    cleaned = re.sub(r'[\u0C80-\u0CFF]', '', cleaned)  # Kannada
    cleaned = re.sub(r'[\u0D00-\u0D7F]', '', cleaned)  # Malayalam
    
    # Remove extra whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    return cleaned


def extract_text_from_pdf(pdf_path):
    """Extract all text from PDF with page number tracking (English only)."""
    try:
        result = {
            'full_text': '',
            'pages': 0,
            'text_by_page': {}
        }
        
        with pdfplumber.open(pdf_path) as pdf:
            result['pages'] = len(pdf.pages)
            logger.info(f"PDF opened: {pdf_path} ({len(pdf.pages)} pages)")
            
            for page_num, page in enumerate(pdf.pages, 1):
                try:
                    text = page.extract_text()
                    if text:
                        # Filter out Hindi and other non-English content
                        cleaned_text = remove_hindi_text(text)
                        if cleaned_text:
                            result['text_by_page'][page_num] = cleaned_text
                            result['full_text'] += f"\n--- PAGE {page_num} ---\n{cleaned_text}"
                except Exception as e:
                    logger.warning(f"Failed to extract text from page {page_num}: {e}")
                    result['text_by_page'][page_num] = ""
            
            logger.info(f"Extracted English text from {len(result['text_by_page'])} pages")
            return result
    
    except Exception as e:
        logger.error(f"Error extracting PDF: {e}")
        raise

def extract_reference_details_from_pdf(pdf_path: str, sub_reference: str, sentence: str, llm_handler) -> dict:
    """
    Extract text from the full PDF and call LLM to find the
    meaning/definition of the sub_reference. Returns the LLM JSON response.
    """
    try:
        if not pdf_path:
            return {"extracted_definition": None, "confidence": "Low", "reasoning": "No PDF path provided"}
            
        import pdfplumber
        text_content = ""
        
        with pdfplumber.open(pdf_path) as pdf:
            max_pages = len(pdf.pages)
            logger.info(f"Extracting details from {pdf_path} (reading all {max_pages} pages)")
            
            for page_num in range(max_pages):
                try:
                    text = pdf.pages[page_num].extract_text()
                    if text:
                        cleaned = remove_hindi_text(text)
                        if cleaned:
                            text_content += f"\n--- PAGE {page_num + 1} ---\n{cleaned}"
                except Exception as e:
                    logger.warning(f"Failed to read page {page_num+1} for detail extraction: {e}")
        
        if not text_content.strip():
            logger.warning(f"No extractable English text found in {pdf_path}")
            return {"extracted_definition": None, "confidence": "Low", "reasoning": "No readable English text in PDF"}
            
        return llm_handler.extract_reference_detail(text_content, sub_reference, sentence)
        
    except Exception as e:
        logger.error(f"Error extracting reference details from {pdf_path}: {e}")
        return {"extracted_definition": None, "confidence": "Low", "reasoning": f"Extraction error: {str(e)}"}