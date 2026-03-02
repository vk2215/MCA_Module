import os
from pymongo import MongoClient
from dotenv import load_dotenv

# Load credentials
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

def test_lookup(search_term):
    client = MongoClient(MONGO_URI)
    db = client["compliance_db"]
    collection = db["knowledge_base"]

    # Convert word to slug (lowercase, underscores) just like we did in extraction
    slug = search_term.lower().strip().replace(" ", "_")

    # Find the document
    result = collection.find_one({"_id": slug})

    if result:
        print(f"\nFOUND: {result['term']}")
        print(f"Chapter: {result['metadata']['chapter']}")
        print("-" * 30)
        print(f"Verbatim:\n{result['verbatim']}")
    else:
        print(f"\nNOT FOUND: No definition for '{search_term}'")

if __name__ == "__main__":
    while True:
        word = input("\nEnter a term to test (or 'exit' to quit): ")
        if word.lower() == 'exit':
            break
        test_lookup(word)