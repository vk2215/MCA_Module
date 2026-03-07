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
ref_collection = db["regulation_references"]

with open("chunks_chapter_wise.json", "r", encoding="utf-8") as f:
    RAW_DATA = json.load(f)

@app.get("/")
def read_root():
    return FileResponse('static/index.html')

'''
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
'''


@app.get("/api/chapters")
def get_chapters_list():
    # 1. Define Roman Numeral weights for logical sorting
    roman_order = {
        'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8,
        'IX': 9, 'X': 10, 'XI': 11, 'XII': 12, 'XIII': 13, 'XIV': 14, 'XV': 15,
        'XVI': 16, 'XVII': 17, 'XVIII': 18, 'XIX': 19, 'XX': 20
    }

    # 2. Only show chapters that have been extracted into regulation_references
    extracted_chapters = ref_collection.distinct("chapter")

    # 3. Sort by Roman numeral order
    return sorted(extracted_chapters, key=lambda x: roman_order.get(x, 99))


'''
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
'''


@app.get("/api/content/{chapter_name}")
def get_chapter_content(chapter_name: str):
    content_blocks = []
    search_term = chapter_name.strip()

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

    '''
    header_pattern = re.compile(
        r'^(CHAPTER|FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|SCHEDULE|PRELIMINARY|PROCEDURE|PART)', 
        re.I
    )'''

    def is_header(text):
        clean = text.strip().replace("**", "")
        if not clean:
            return False

        # Pattern A: Chapter / Schedule / Part / Preliminary
        if re.match(r'^(CHAPTER|SCHEDULE|PART|PRELIMINARY|FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|ANNEXURE)\b', clean, re.I):
            return True
        
        # Pattern B: ALL CAPS headings
        if clean.isupper() and len(clean) > 4:
            return True

        return False

    reg_refs = list(ref_collection.find({"chapter": search_term}))
    print(f"DEBUG API: Found {len(reg_refs)} reg_refs for {search_term}")
    reg_refs.sort(key=lambda x: len(x['reference_text']), reverse=True)

    updated_lines = []
    for line in lines:
        stripped = line.strip().replace("**", "")

        if re.match(r'^(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH)\s+SCHEDULE\b', stripped, re.I):
            updated_lines.append("")
            updated_lines.append('<div class="pdf-page-break"></div>')
            updated_lines.append(f'<div class="sch-header">{stripped}</div>')
            continue

        updated_lines.append(line)

    lines = updated_lines
    print(f"DEBUG API: Lines count: {len(lines)}")

    repaired_lines = []
    for i in range(len(lines)):
        current_line = lines[i]
        repaired_lines.append(current_line)
        
        if current_line.strip().startswith("|") and i + 1 < len(lines):
            next_line = lines[i+1].strip()
            if next_line and not next_line.startswith("|"):
                repaired_lines.append("")

    lines = repaired_lines

    if "|" in full_text and "|---" not in full_text:
        for i, line in enumerate(lines):
            if "|" in line and i + 1 < len(lines) and "|" in lines[i+1]:
                cols = line.count("|") - 1
                lines.insert(i+1, "|" + "---|" * cols)
                break
    
    # 4. Highlighting and Hover Logic
    
    # Normalize and sort regulation references
    cleaned_reg_refs = []
    for ref in reg_refs:
        text = ref['reference_text'].strip()
        if text.endswith('.') and not re.search(r'\d\.$', text): 
            text = text[:-1].strip()
        if len(text) > 3:
            cleaned_reg_refs.append(text)
    
    cleaned_reg_refs = sorted(list(set(cleaned_reg_refs)), key=len, reverse=True)
    print(f"DEBUG API: Cleaned {len(cleaned_reg_refs)} refs")

    # Prepare lines with basic formatting first
    formatted_lines = []
    for line in lines:
        stripped = line.strip().replace("**", "")
        if is_header(stripped):
            formatted_lines.append(f"**{stripped}**")
        else:
            formatted_lines.append(line)
    
    full_text = "\n".join(formatted_lines)
    print(f"DEBUG API: full_text length: {len(full_text)}")

    # 1. Apply Regulation Highlighting (on the full text to handle multi-line)
    highlight_count = 0
    for ref_text in cleaned_reg_refs:
        words = ref_text.split()
        if not words: continue
        regex_pattern = r'[\s\n]+'.join(map(re.escape, words))
        pattern = re.compile(rf'(?<!\w){regex_pattern}(?!\w)', re.IGNORECASE)
        
        matches = pattern.findall(full_text)
        if matches:
            highlight_count += len(matches)
            full_text = pattern.sub(r'<strong class="reg-bold-highlight">\g<0></strong>', full_text)
    
    print(f"DEBUG API: highlight_count: {highlight_count}")

    # 2. Apply Glossary Hover Terms
    glossary_items = list(collection.find({}, {"_id": 1, "term": 1}))
    glossary_items.sort(key=lambda x: len(x['term']), reverse=True)
    
    for item in glossary_items:
        term = item['term']
        t_id = item['_id']
        # For glossary, we still want to avoid matching inside the strong tags we just added
        pattern = re.compile(rf'\b({re.escape(term)})\b(?![^<]*>)', re.IGNORECASE)
        full_text = pattern.sub(f'<span class="hover-term" data-id="{t_id}">\\1</span>', full_text)

    return {"chapter": chapter_name, "html_content": full_text}




@app.get("/api/definition/{term_id}")
def get_definition(term_id: str):
    result = collection.find_one({"_id": term_id})
    if not result:
        raise HTTPException(status_code=404, detail="Definition not found")
    return result