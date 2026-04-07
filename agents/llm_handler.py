import json
import logging
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from agents.prompt import REFERENCE_EXTRACTION_PROMPT

logger = logging.getLogger("ReferenceExtraction")

load_dotenv()


class LLMHandler:
    """Handles LLM interactions with Google Gemini."""

    def __init__(self):
        """Initialize Gemini API client."""
        try:
            api_key    = os.getenv("GEMINI_API_KEY")
            model_name = os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")

            if not api_key:
                raise ValueError("GOOGLE_API_KEY not found in .env")

            self.client     = genai.Client(api_key=api_key)
            self.model_name = model_name
            logger.info(f"Initialized Gemini Model: {model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
            raise

    def extract_references(self, text: str) -> list:
        """
        Call Gemini once with REFERENCE_EXTRACTION_PROMPT.
        Returns a list of dicts: [{reference, sub_reference}, ...]
        exactly as the model produces them — no further LLM calls needed.
        """
        try:
            prompt = self._render_prompt(REFERENCE_EXTRACTION_PROMPT, text=text)

            logger.debug("Calling Gemini for reference extraction...")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            raw = json.loads(response.text.strip())

            # Normalise to always be a list of dicts
            if isinstance(raw, dict):
                raw = [raw]
            if not isinstance(raw, list):
                return []

            references = []
            seen       = set()
            for item in raw:
                if not isinstance(item, dict):
                    continue
                ref = item.get("reference", "").strip()
                sentence = item.get("sentence", "").strip()
                source = item.get("source")
                
                # Deduplicate by reference + sentence exactly as instructed
                dedup_key = f"{ref.lower()}_{sentence.lower()}"
                if not ref or dedup_key in seen:
                    continue
                seen.add(dedup_key)
                sub_ref = item.get("sub_reference")
                source = item.get("source")
                references.append({
                    "reference":     ref,
                    "sub_reference": sub_ref if isinstance(sub_ref, str) and sub_ref.strip().lower() not in ("", "null") else None,
                    "sentence":      sentence if isinstance(sentence, str) and sentence.strip() else None,
                    "source":        source if isinstance(source, str) and source.strip() else None,
                })

            logger.info(f"Extracted {len(references)} unique references from PDF")
            return references

        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error in reference extraction: {e}")
            return []
        except Exception as e:
            logger.error(f"Error during reference extraction: {e}")
            return []

    def _render_prompt(self, template: str, **kwargs) -> str:
        """
        Replace named placeholders without touching JSON braces in examples.
        Uses simple string replace instead of str.format() to avoid collisions.
        """
        rendered = template
        for key, value in kwargs.items():
            rendered = rendered.replace("{" + key + "}", str(value))
        return rendered

    def _clean_llm_json(self, raw_text: str) -> str:
        """
        Clean LLM response to ensure it's valid JSON.
        - Strips Markdown code blocks.
        - Removes leading/trailing whitespace.
        - Fixes common unescaped character issues.
        """
        if not raw_text:
            return ""
        
        cleaned = raw_text.strip()
        
        # Remove Markdown code blocks if present
        if cleaned.startswith("```"):
            # Matches ```json ... ``` or just ``` ... ```
            match = re.search(r'```(?:json)?\s*(.*?)\s*```', cleaned, re.DOTALL)
            if match:
                cleaned = match.group(1).strip()
        
        # Basic sanity check — must start with { or [
        if not (cleaned.startswith("{") or cleaned.startswith("[")):
            # Try to find the first { and last }
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1:
                cleaned = cleaned[start:end+1]

        return cleaned

    def extract_reference_detail(self, text: str, sub_reference: str, sentence: str) -> dict:
        """
        Call Gemini to extract the specific meaning/definition of a sub_reference
        from the provided PDF text. Includes retry logic for 429 rate limits 
        and JSON decoding errors.
        """
        try:
            from agents.prompt import REFERENCE_DETAIL_EXTRACTION_PROMPT
            import time
            from google.api_core import exceptions as google_exceptions
            
            prompt = self._render_prompt(
                REFERENCE_DETAIL_EXTRACTION_PROMPT, 
                text=text, 
                sub_reference=sub_reference if sub_reference else "the main focus of the document", 
                sentence=sentence
            )

            max_retries = 3
            base_delay = 15  # seconds
            
            for attempt in range(max_retries):
                try:
                    logger.debug(f"Calling Gemini for reference detail extraction... (Attempt {attempt + 1}/{max_retries})")
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                        ),
                    )
                    
                    cleaned_response = self._clean_llm_json(response.text)
                    try:
                        raw = json.loads(cleaned_response)
                    except json.JSONDecodeError as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"JSON decode failed on attempt {attempt + 1}. Retrying with stricter instructions...")
                            # Add a "nudge" to the prompt for the retry
                            prompt += "\n\nCRITICAL: Your previous response was not valid JSON. Please ensure all double quotes within strings are escaped as \\\" and the JSON is properly terminated."
                            time.sleep(2)
                            continue
                        else:
                            raise e
                    
                    if not isinstance(raw, dict):
                        return {"extracted_definition": None, "document_summary": None, "confidence": "Low", "reasoning": "Invalid LLM output format"}
                        
                    return raw
                    
                except google_exceptions.ResourceExhausted as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Gemini API rate limit hit (429). Waiting {base_delay} seconds before retry...")
                        time.sleep(base_delay)
                        base_delay *= 2  # Exponential backoff
                    else:
                        logger.error(f"Failed to extract after {max_retries} attempts due to rate limit: {e}")
                        return {
                            "extracted_definition": None, 
                            "meaningful_context": None, 
                            "confidence": "Low", 
                            "reasoning": "Rate limit exceeded",
                            "location_metadata": {},
                            "source_url": None
                        }
                except Exception as e:
                    # For other exceptions, if it's the last attempt, raise; else retry
                    if attempt < max_retries - 1:
                        logger.warning(f"Unexpected error on attempt {attempt + 1}: {e}. Retrying...")
                        time.sleep(2)
                        continue
                    raise e

        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error after {max_retries} attempts: {e}")
            return {
                "extracted_definition": None, 
                "meaningful_context": None, 
                "confidence": "Low", 
                "reasoning": f"JSON decode error: {e}",
                "location_metadata": {},
                "source_url": None
            }
        except Exception as e:
            logger.error(f"Error during detail extraction: {e}")
            return {
                "extracted_definition": None, 
                "meaningful_context": None, 
                "confidence": "Low", 
                "reasoning": str(e),
                "location_metadata": {},
                "source_url": None
            }