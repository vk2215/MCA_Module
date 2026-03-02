import os
import re
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

client = MongoClient(os.getenv("MONGO_URI"))
db = client["compliance_db"]
collection = db["knowledge_base"]

with open("chunks_chapter_wise.json", "r", encoding="utf-8") as f:
    RAW_DATA = json.load(f)

@app.get("/")
def read_root():
    return FileResponse('static/index.html')

@app.get("/api/chapters")
def get_chapters_list():
    chapters = []
    seen = set()
    for chunk in RAW_DATA.get('chunks', []):
        metadata = chunk.get('Metadata') or chunk.get('metadata') or {}
        # Get raw chapter info (e.g. "**Chapter I**" or "I")
        chapter_raw = metadata.get('Chapter') or metadata.get('chapter')
        
        if chapter_raw:
            # Clean it to just the Roman Numeral or Name
            c_name = str(chapter_raw).replace("**", "").replace("Chapter", "").strip()
            if c_name and c_name not in seen:
                chapters.append(c_name)
                seen.add(c_name)
    
    # Sort them logically if they are Roman Numerals
    return sorted(list(chapters))

@app.get("/api/content/{chapter_name}")
def get_chapter_content(chapter_name: str):
    content_blocks = []
    search_term = chapter_name.strip()

    # 1. Flexible Matching to find the content
    for c in RAW_DATA.get('chunks', []):
        metadata = c.get('Metadata') or c.get('metadata') or {}
        raw_val = str(metadata.get('Chapter') or metadata.get('chapter', ""))
        clean_val = raw_val.replace("**", "").replace("Chapter", "").strip()
        
        if clean_val == search_term:
            content_blocks.append(c.get('Content', ""))
            
    if not content_blocks:
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_name} not found")

    full_text = "\n\n".join(content_blocks)
    lines = full_text.split("\n")

    # 2. Table Separation Logic
    # Injects a newline if a non-table line immediately follows a table line.
    repaired_lines = []
    for i in range(len(lines)):
        current_line = lines[i]
        repaired_lines.append(current_line)
        
        # Check if current line is part of a table and there is a next line
        if current_line.strip().startswith("|") and i + 1 < len(lines):
            next_line = lines[i+1].strip()
            # If next line is NOT a table line, force a break
            if next_line and not next_line.startswith("|"):
                repaired_lines.append("") # Adds an empty string resulting in a double \n

    lines = repaired_lines

    # 3. Table Protection & Fixer (Existing)
    if "|" in full_text and "|---" not in full_text:
        for i, line in enumerate(lines):
            if "|" in line and i + 1 < len(lines) and "|" in lines[i+1]:
                cols = line.count("|") - 1
                lines.insert(i+1, "|" + "---|" * cols)
                break
    
    # 4. Auto-Linker
    if search_term != "I":
        glossary_items = list(collection.find({}, {"_id": 1, "term": 1}))
        glossary_items.sort(key=lambda x: len(x['term']), reverse=True)
        
        final_lines = []
        for line in lines:
            # Don't add hover spans inside table rows
            if line.strip().startswith("|"):
                final_lines.append(line)
                continue
            
            for item in glossary_items:
                term = item['term']
                t_id = item['_id']
                pattern = re.compile(rf'\b({re.escape(term)})\b', re.IGNORECASE)
                line = pattern.sub(f'<span class="hover-term" data-id="{t_id}">\\1</span>', line)
            final_lines.append(line)
        full_text = "\n".join(final_lines)
    else:
        full_text = "\n".join(lines)

    return {"chapter": chapter_name, "html_content": full_text}



@app.get("/api/definition/{term_id}")
def get_definition(term_id: str):
    result = collection.find_one({"_id": term_id})
    if not result:
        raise HTTPException(status_code=404, detail="Definition not found")
    return result