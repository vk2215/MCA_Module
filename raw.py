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

    with open("chunks_chapter_wise.json", 'r', encoding='utf-8') as f:
        data = json.load(f)

    regex_pattern = r"\(([a-z]+)\)\s*[“\"']([^”\"']*)[\"”']\s+(.*?)(?=\n\s*\([a-z]\)|\n\s*\*\*|$)"
    
    final_glossary = []

    print("Processing Chunks...")
    for chunk in data['chunks']:
        chapter = chunk.get("Metadata", {}).get("Chapter", "Unknown").replace("**", "")
        content = chunk.get("Content", "")

        matches = re.findall(regex_pattern, content, re.DOTALL)

        for sub_point, term, verbatim in matches:
            
            slug = term.lower().strip().replace(" ", "_").replace('"', '').replace('“', '')
            
            doc = {
                "_id": slug,
                "term": term.strip(),
                "verbatim": verbatim.strip().replace("\n", " "),
                "metadata": {
                    "chapter": chapter,
                    "sub_point": sub_point,
                }
            }
            final_glossary.append(doc)
            
           
            collection.update_one({"_id": slug}, {"$set": doc}, upsert=True)

   
    with open("definitions.json", "w", encoding="utf-8") as f:
        json.dump(final_glossary, f, indent=4)

    print(f"Success! {len(final_glossary)} definitions stored.")
    print("Local File Generated: 'definitions.json'")

if __name__ == "__main__":
    extract_chapter_wise('chunks_chapter_wise.json')