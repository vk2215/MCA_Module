import json
import os
import time
import re
import google.generativeai as genai
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# ---------------------------
# 1. LLM SETUP
# ---------------------------
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")

# ---------------------------
# 2. DATABASE SETUP
# ---------------------------
client = MongoClient(os.getenv("MONGO_URI"))
db = client["compliance_db"]
ref_collection = db["regulation_references"]


# ---------------------------
# CLEAN LLM RESPONSE
# ---------------------------
def clean_llm_json(text):
    """
    Removes markdown code blocks and extracts valid JSON.
    """
    text = text.strip()

    # Remove ```json or ``` wrappers
    text = re.sub(r"```json", "", text)
    text = re.sub(r"```", "", text)

    # Extract JSON array if extra text exists
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        text = match.group(0)

    return text


# ---------------------------
# LLM EXTRACTION
# ---------------------------
def extract_regulations_with_llm(text):

    prompt = f"""
You are a legal citation parser.

Extract ONLY:
1. Formal citations to regulations (regulation 7, sub-regulation (1), clause (a))
2. References to external Acts or laws (Companies Act 2013, SEBI Act 1992)
3. Explicit provision references

SKIP:
- Definitions (mutual fund, sponsor, trustee etc.)
- Internal headers (Explanation, Note)
- Schedules unless external law
- Phrases like "these regulations"

Return ONLY JSON list.

Format:
[
 {{
  "reference_text": "...",
  "regulation_name": "...",
  "year": "...",
  "reference_type": "...",
  "point": "..."
 }}
]

Text:
{text}
"""

    try:

        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )

        cleaned = clean_llm_json(response.text)

        data = json.loads(cleaned)

        if isinstance(data, list):
            return data
        else:
            return []

    except Exception as e:
        print("LLM parsing error:", e)
        return []


# ---------------------------
# MAIN PROCESSOR
# ---------------------------
def process_regulations(file_path):

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    seen = set()
    all_refs = []

    print("Starting regulation extraction...\n")

    for chunk in data.get("chunks", []):

        metadata = chunk.get("Metadata") or chunk.get("metadata") or {}

        chapter = str(
            metadata.get("Chapter") or metadata.get("chapter") or "Unknown"
        ).replace("**", "").strip()

        # PROCESS ONLY CHAPTER I–VI
        if chapter not in ["I", "II", "III", "IV", "V", "VI"]:
            continue

        content = chunk.get("Content", "").strip()

        if not content:
            continue

        print(f"Processing Chapter {chapter}")

        refs = extract_regulations_with_llm(content)

        for ref in refs:

            reference_text = ref.get("reference_text", "").strip()

            if not reference_text:
                continue

            # Deduplication key
            key = (chapter, reference_text)

            if key in seen:
                continue

            seen.add(key)

            entry = {
                "chapter": chapter,
                "reference_text": reference_text,
                "regulation_name": ref.get("regulation_name", "Unknown"),
                "year": ref.get("year", ""),
                "reference_type": ref.get("reference_type", ""),
                "point": ref.get("point", "")
            }

            all_refs.append(entry)

            # UPSERT TO MONGODB
            ref_collection.update_one(
                {
                    "reference_text": entry["reference_text"],
                    "chapter": chapter
                },
                {"$set": entry},
                upsert=True
            )

        # Avoid Gemini rate limit
        time.sleep(0.7)

    # SAVE LOCAL FILE
    with open("extracted_regulations.json", "w", encoding="utf-8") as f:
        json.dump(all_refs, f, indent=4)

    print("\nExtraction Complete")
    print(f"Total references found: {len(all_refs)}")


# ---------------------------
# ENTRY POINT
# ---------------------------
if __name__ == "__main__":
    process_regulations("chunks_chapter_wise.json")