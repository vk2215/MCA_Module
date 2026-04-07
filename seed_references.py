"""
Seed STEP-02_reference_details.json into MongoDB reference_details collection.
Run this once (or whenever the JSON changes) to populate/refresh the collection.
"""

import os
import re
import json
import hashlib
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

DETAIL_JSON = os.path.join("output", "STEP-02_reference_details.json")
MONGO_URI   = os.getenv("MONGO_URI")
DB_NAME     = "compliance_db"
COLL_NAME   = "reference_details"


def main():
    path = Path(DETAIL_JSON)
    if not path.exists():
        print(f"ERROR: {DETAIL_JSON} not found. Run reference_handler.py first.")
        return

    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)

    print(f"Connecting to MongoDB...")
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
        client.admin.command("ping")
        print("MongoDB Atlas Connected.")
    except Exception as e:
        print(f"Connection Error: {e}")
        return

    db   = client[DB_NAME]
    coll = db[COLL_NAME]

    print(f"Clearing old records from '{COLL_NAME}'...")
    deleted = coll.delete_many({})
    print(f"  Removed {deleted.deleted_count} old records.")

    count = 0
    for record in records:
        ref_text = record.get("reference", "") or ""
        sentence = record.get("sentence", "") or ""
        # Build _id based on reference name + sentence to ensure identical 
        # regulations with different context sentences don't overwrite each other.
        hash_input = f"{ref_text}_{sentence}".encode('utf-8')
        doc_id = hashlib.md5(hash_input).hexdigest()
        
        if not ref_text.strip():
            continue

        doc = {
            "_id":               doc_id,
            "reference":         ref_text,
            "sub_reference":     record.get("sub_reference"),
            "sentence":          record.get("sentence"),
            "source":            record.get("source"),
            "pdf_path":          record.get("pdf_path"),
            "source_pdf_url":    record.get("source_pdf_url"),
            "extracted_details": record.get("extracted_details", {}),
        }

        coll.update_one({"_id": doc_id}, {"$set": doc}, upsert=True)
        count += 1
        print(f"  [{count}] Upserted: {ref_text[:80]}")

    print(f"\nDone! {count} records upserted into '{DB_NAME}.{COLL_NAME}'.")


if __name__ == "__main__":
    main()