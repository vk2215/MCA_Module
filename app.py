import json
import re
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "compliance_db"
COLLECTION_NAME = "knowledge_base"

def extract_chapter_wise(file_path):
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        print("MongoDB Atlas Connected.")
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]
    except Exception as e:
        print(f"Connection Error: {e}")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # --- NEW OPTIMIZED REGEX ---
    # 1. Matches (a), (aa), or (aaa) followed by "Term"
    # 2. Captures EVERYTHING (including (i), (ii), (iii)) 
    # 3. Stops ONLY when it sees a newline followed by the next alphabetical index like (b) or (ab)
    # The pattern (?=\n\s*\([a-z]{1,3}\)\s*[“\"']) is the key "Lookahead" stop.
    regex_pattern = r"\(([a-z]{1,3})\)\s*[“\"']([^”\"']*)[\"”']\s+(.*?)(?=\n\s*\([a-z]{1,3}\)\s*[“\"']|\n\s*\*\*|\Z)"
    
    final_glossary = []

    print("Processing Chunks...")
    for chunk in data.get('chunks', []):
        chapter = chunk.get("Metadata", {}).get("Chapter", "Unknown").replace("**", "")
        content = chunk.get("Content", "")

        # finditer allows us to process multi-line blocks correctly
        matches = re.finditer(regex_pattern, content, re.DOTALL)

        for match in matches:
            index_marker = match.group(1) # a, b, aa, etc.
            term = match.group(2).strip()   # The word inside quotes
            verbatim = match.group(3).strip() # Everything after the quotes until the next term
            
            # Clean the verbatim text: 
            # We keep the newlines for sub-points (i), (ii) so they look good in the hover box
            clean_verbatim = verbatim.replace("  ", " ").strip()
            
            slug = term.lower().strip().replace(" ", "_").replace('"', '').replace('“', '').replace('”', '')
            
            doc = {
                "_id": slug,
                "term": term,
                "verbatim": clean_verbatim,
                "metadata": {
                    "chapter": chapter,
                    "index_marker": index_marker,
                }
            }
            final_glossary.append(doc)
            
            # Upsert into MongoDB
            collection.update_one({"_id": slug}, {"$set": doc}, upsert=True)

    # Save locally for verification
    with open("definitions.json", "w", encoding="utf-8") as f:
        json.dump(final_glossary, f, indent=4)

    print(f"Success! Extracted {len(final_glossary)} terms.")

if __name__ == "__main__":
    extract_chapter_wise('chunks_chapter_wise.json')