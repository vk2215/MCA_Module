import json
import os
import re
import google.generativeai as genai  # pip install google-generativeai
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# 1. SETUP LLM
genai.configure(api_key=os.getenv("INTERNAL_HDFC"))
model = genai.GenerativeModel('gemini-2.5-flash') # Or gemini-pro

# 2. SETUP DATABASE
client = MongoClient(os.getenv("MONGO_URI"))
db = client["compliance_db"]
ref_collection = db["regulation_references"]

def extract_regulations_with_llm(text):
    """
    Passes the chunk to the LLM and returns a clean list of regulation references.
    """
    # SYSTEM PROMPT
    prompt = f"""
    Act as a legal document parser. Your goal is to extract ONLY formal citations and references to specific legal provisions OR references to OTHER external documents/Acts/Regulations.
    
    CRITICAL INSTRUCTIONS - WHAT TO EXTRACT:
    - Formal citations to specific regulations, sub-regulations, sections, and clauses (e.g., 'regulation 7', 'sub-regulation (1)', 'clause (a) of regulation 4').
    - ALL formal references to EXTERNAL documents, Acts, or Regulations (e.g., 'Securities and Exchange Board of India Act, 1992', 'Companies Act, 2013', 'Registration Act, 1908').
    - References to specific points or notes ONLY if they are part of a formal provision citation.

    CRITICAL INSTRUCTIONS - WHAT TO SKIP (IMPORTANT):
    - SKIP generic legal terms and internal definitions like 'trust deed', 'mutual fund', 'sponsor', 'offer document', 'scheme', 'unitholders', 'asset management company'.
    - SKIP internal document markers like 'First Schedule', 'Second Schedule', 'Schedule', 'Annexure', 'Appendix' unless they refer to an EXTERNAL document's schedule.
    - SKIP internal structural headers like 'Explanation', 'Note', or 'Clause' when used as a header for current content.
    - SKIP phrases like 'these regulations' or 'provided under regulation' without a specific number.

    Return the results ONLY as a JSON list of objects with these keys: 
    - 'reference_text': the full original citation string (e.g., 'the Registration Act, 1908', 'regulation 7').
    - 'regulation_name': the name of the main regulation or document being referenced (e.g., 'Registration Act').
    - 'year': the year mentioned in the reference, if any.
    - 'reference_type': the type of reference ('regulation', 'section', 'clause', 'sub-clause', 'sub-regulation', 'point', 'note', 'schedule', 'act').
    - 'point': the specific point or sub-clause number/identifier (e.g., '7', '1', 'ab').

    If no formal regulations or external cross-references are found, return an empty list []. Do not explain your reasoning.
    
    Text to process:
    {text}
    """

    try:
        # Requesting JSON specifically
        response = model.generate_content(
            prompt, 
            generation_config={"response_mime_type": "application/json"}
        )
        
        # Parse the JSON string from the LLM
        return json.loads(response.text)
    
    except Exception as e:
        print(f"LLM Error: {e}")
        return []

def process_regulations(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    all_extracted_refs = []

    print("Extracting regulation references using LLM...")
    for chunk in data.get('chunks', []):
        # Normalizing chapter value
        metadata = chunk.get("Metadata") or chunk.get("metadata") or {}
        chapter = str(metadata.get("Chapter") or metadata.get("chapter", "Unknown")).replace("**", "").strip()

        content = chunk.get("Content", "")
        if not content.strip():
            continue

        print(f"Processing Chapter {chapter}...")
        
        # Only process Chapters I through VI as requested
        if chapter not in ["I", "II", "III", "IV", "V", "VI"]:
            print(f"Skipping Chapter {chapter} (out of range I-VI)...")
            continue

        found_refs = extract_regulations_with_llm(content)

        for ref in found_refs:
            entry = {
                "chapter": chapter,
                "reference_text": ref.get("reference_text", "").strip().replace("\n", " "),
                "regulation_name": ref.get("regulation_name", "Unknown"),
                "year": ref.get("year", ""),
            }
            
            all_extracted_refs.append(entry)
            
            # Upsert into DB
            ref_collection.update_one(
                {"reference_text": entry["reference_text"], "chapter": chapter},
                {"$set": entry},
                upsert=True
            )

    # Local save for verification
    with open("extracted_regulations.json", "w", encoding="utf-8") as f:
        json.dump(all_extracted_refs, f, indent=4)
    
    print(f"Extraction complete. Found {len(all_extracted_refs)} references.")

if __name__ == "__main__":
    process_regulations('chunks_chapter_wise.json')