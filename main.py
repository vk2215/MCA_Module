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

@app.get("/api/chapters")
def get_chapters_list():
    roman_order = {
        'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 
        'IX': 9, 'X': 10, 'XI': 11, 'XII': 12, 'XIII': 13, 'XIV': 14, 'XV': 15, 
        'XVI': 16, 'XVII': 17, 'XVIII': 18, 'XIX': 19, 'XX': 20
    }
    
    chapters = set() # Use a set to automatically handle uniqueness
    for chunk in RAW_DATA.get('chunks', []):
        metadata = chunk.get('Metadata') or chunk.get('metadata') or {}
        chapter_raw = metadata.get('Chapter') or metadata.get('chapter')
        
        if chapter_raw:
            # Clean string: Remove **, remove 'Chapter', strip whitespace and trailing punctuation
            c_name = str(chapter_raw).replace("**", "").replace("Chapter", "").strip().rstrip('.')
            if c_name:
                chapters.add(c_name)
    
    # Sort by Roman weight; non-Roman names default to 99 (end of list)
    return sorted(list(chapters), key=lambda x: roman_order.get(x, 99))

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

    def is_header(text):
        clean = text.strip().replace("**", "")
        if not clean:
            return False

        # Pattern A: Chapter / Schedule / Part / Preliminary / Annexure
        if re.match(r'^(CHAPTER|SCHEDULE|PART|PRELIMINARY|FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|ANNEXURE)\b', clean, re.I):
            return True
        
        # Pattern B: ALL CAPS headings (usually titles)
        if clean.isupper() and len(clean) > 4:
            return True

        # Pattern C: Regulation-level titles (e.g., "12. Rights and obligations...")
        # These usually start with a number followed by a dot and some text, 
        # and are relatively short (e.g., < 150 chars)
        if re.match(r'^\d+\.\s+.+', clean) and len(clean) < 150:
            return True

        return False

    # Get regulation references and glossary items once
    reg_refs = list(ref_collection.find({"chapter": search_term}))
    glossary_items = list(collection.find({}, {"_id": 1, "term": 1}))
    glossary_items.sort(key=lambda x: len(x['term']), reverse=True)

    # Normalize regulation references for matching
    cleaned_reg_refs = []
    for ref in reg_refs:
        text = ref['reference_text'].strip()
        if text.endswith('.') and not re.search(r'\d\.$', text): 
            text = text[:-1].strip()
        if len(text) > 3:
            cleaned_reg_refs.append(text)
    cleaned_reg_refs = sorted(list(set(cleaned_reg_refs)), key=len, reverse=True)

    processed_lines = []
    
    # 2. Process line by line
    for i, line in enumerate(lines):
        stripped = line.strip().replace("**", "")
        if not stripped:
            processed_lines.append(line)
            continue

        # Skip redundant Chapter headers (e.g., "CHAPTER III")
        # because the frontend already adds a huge <h1>Chapter III</h1>
        if re.match(rf'^CHAPTER\s+{re.escape(search_term)}\b', stripped, re.I):
            continue

        # Handle Schedule headers with page breaks
        if re.match(r'^(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH)\s+SCHEDULE\b', stripped, re.I):
            processed_lines.append('<div class="pdf-page-break"></div>')
            processed_lines.append(f'<div class="sch-header">{stripped}</div>')
            continue

        if is_header(stripped):
            # It's a header: bold it but DO NOT apply glossary/reg highlights
            processed_lines.append(f"**{stripped}**")
        else:
            # It's body text: apply highlights and glossary
            current_text = line
            
            # Apply Regulation Highlighting
            for ref_text in cleaned_reg_refs:
                words = ref_text.split()
                if not words: continue
                regex_pattern = r'[\s\n]+'.join(map(re.escape, words))
                pattern = re.compile(rf'(?<!\w){regex_pattern}(?!\w)', re.IGNORECASE)
                current_text = pattern.sub(r'<strong class="reg-bold-highlight">\g<0></strong>', current_text)

            # Apply Glossary Hover Terms
            for item in glossary_items:
                term = item['term']
                t_id = item['_id']
                # Avoid matching inside tags (like <strong> or <span>)
                pattern = re.compile(rf'\b({re.escape(term)})\b(?![^<]*>)', re.IGNORECASE)
                current_text = pattern.sub(f'<span class="hover-term" data-id="{t_id}">\\1</span>', current_text)
            
            processed_lines.append(current_text)

    # 3. Smart Table Rebuilder
    # The source JSON has tables where PDF-overflow text is stored as continuation rows:
    #   |Col1|Col2|Col3| overflow text goes here |
    # and misplaced |---|---| separators after them.
    # We: 1) merge continuation rows into the previous data row
    #     2) strip errant separators
    #     3) insert ONE correct separator after the true header row

    def is_separator(line):
        stripped = line.strip()
        return bool(stripped) and all(c in '|-: ' for c in stripped)

    def is_col_placeholder(line):
        """Detect lines whose cells are only ColN placeholders (e.g. |Col1|Col2|Col3|)."""
        stripped = line.strip().strip('|')
        if not stripped:
            return False
        cells = [c.strip() for c in stripped.split('|')]
        return all(re.match(r'^Col\d+$', c, re.I) for c in cells if c)

    def parse_cells(line):
        """Split a pipe-row into list of cell strings."""
        return [c.strip() for c in line.strip().strip('|').split('|')]

    def merge_continuation_row(base_cells, cont_cells):
        """Append continuation cell text into base_cells at matching positions."""
        result = list(base_cells)
        for idx, cell in enumerate(cont_cells):
            if idx < len(result):
                if cell:  # only merge non-empty continuation cells
                    result[idx] = (result[idx] + ' ' + cell).strip()
        return result

    def build_row(cells):
        return '| ' + ' | '.join(cells) + ' |'

    # Iterate processed_lines; collect table blocks and rebuild them
    merged_final = []
    idx = 0
    while idx < len(processed_lines):
        line = processed_lines[idx]
        if not line.strip().startswith('|'):
            merged_final.append(line)
            idx += 1
            continue

        # Collect entire table island
        table_block = []
        while idx < len(processed_lines) and (processed_lines[idx].strip().startswith('|') or not processed_lines[idx].strip()):
            if processed_lines[idx].strip():
                table_block.append(processed_lines[idx])
            idx += 1

        # --- Rebuild the table ---
        # Step A: remove all separator lines (we'll add one correct one later)
        rows_no_sep = [ln for ln in table_block if not is_separator(ln)]

        if not rows_no_sep:
            merged_final.extend(table_block)
            continue

        # Step B: merge continuation rows (|Col1|Col2|...) into the previous data row
        merged_rows = []
        for raw_row in rows_no_sep:
            if is_col_placeholder(raw_row):
                if merged_rows:
                    base_cells = parse_cells(merged_rows[-1])
                    cont_cells = parse_cells(raw_row)
                    merged_rows[-1] = build_row(merge_continuation_row(base_cells, cont_cells))
                # else discard orphan continuation row with no parent
            else:
                merged_rows.append(raw_row)

        # Step C: determine column count from first data row
        if not merged_rows:
            merged_final.extend(table_block)
            continue

        num_cols = max(r.count('|') - 1 for r in merged_rows)

        # Step D: pad every row to num_cols cells to keep table rectangular
        padded_rows = []
        for row in merged_rows:
            cells = parse_cells(row)
            while len(cells) < num_cols:
                cells.append('')
            padded_rows.append(build_row(cells[:num_cols]))

        # Step E: insert separator after row 0 (the header)
        separator = '| ' + ' | '.join(['---'] * num_cols) + ' |'
        rebuilt = [padded_rows[0], separator] + padded_rows[1:]
        merged_final.extend(rebuilt)
        merged_final.append('')  # blank line to terminate table block

    return {"chapter": chapter_name, "html_content": "\n".join(merged_final)}




@app.get("/api/definition/{term_id}")
def get_definition(term_id: str):
    result = collection.find_one({"_id": term_id})
    if not result:
        raise HTTPException(status_code=404, detail="Definition not found")
    return result