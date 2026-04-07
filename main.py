import os
import re
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

client = MongoClient(os.getenv("MONGO_URI"))  # original — works on other machines
# macOS SSL fix (local only — revert before deploying):
# import certifi
# client = MongoClient(os.getenv("MONGO_URI"), tlsCAFile=certifi.where())
db = client["compliance_db"]
collection = db["knowledge_base"]
ref_collection = db["regulation_references"]
reference_details_coll = db["reference_details"]

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

    # Pre-fetch items
    reg_refs = list(ref_collection.find({"chapter": search_term}))
    glossary_items = list(collection.find({}, {"_id": 1, "term": 1}))
    glossary_items.sort(key=lambda x: len(x['term']), reverse=True)
    
    reference_items = list(reference_details_coll.find({}, {"_id": 1, "reference": 1}))
    reference_items.sort(key=lambda x: len(x.get('reference', '')), reverse=True)

    cleaned_reg_refs = []
    for ref in reg_refs:
        text = ref['reference_text'].strip()
        if text.endswith('.') and not re.search(r'\d\.$', text): 
            text = text[:-1].strip()
        if len(text) > 3:
            cleaned_reg_refs.append(text)
    cleaned_reg_refs = sorted(list(set(cleaned_reg_refs)), key=len, reverse=True)

    # Apply Highlighting on the Entire Text Block (allows multi-line matching)
    # --- HIGHLIGHTING TRACKER ---
    # Frequency limit: 3 times per unique term per chapter.
    occurrence_tracker = {}

    def get_replacement(match, t_id, category, limit=3):
        # The text actually matched in the document
        orig_text = match.group(1)
        # Use lowercase normalized text for global counting across categories
        norm_text = orig_text.lower().strip()
        
        # We track by BOTH category/ID and the visual text to be strictly 3.
        track_key_id = f"{category}_{t_id}"
        track_key_text = f"text_{norm_text}"
        
        count_id = occurrence_tracker.get(track_key_id, 0)
        count_text = occurrence_tracker.get(track_key_text, 0)
        
        if count_id < limit and count_text < limit:
            occurrence_tracker[track_key_id] = count_id + 1
            occurrence_tracker[track_key_text] = count_text + 1
            
            if category == "ref":
                return f'<span class="hover-ref" data-ref-id="{t_id}">{orig_text}</span>'
            elif category == "reg":
                return f'<strong class="reg-bold-highlight">{orig_text}</strong>'
            elif category == "glossary":
                return f'<span class="hover-term" data-id="{t_id}">{orig_text}</span>'
        
        return orig_text

    # 1. References (Major Acts) — NAME-FIRST CONTEXT-AWARE HIGHLIGHTER
    # Step A: Group all records by their reference name
    from collections import defaultdict
    ref_map = defaultdict(list)
    for ref_item in list(reference_details_coll.find({})):
        name = ref_item.get('reference', '').strip()
        if name:
            # Clean name for keying (remove act numbers)
            clean_key = re.sub(r'\s*\(\d+\s+of\s+\d+\)$', '', name).strip().lower()
            ref_map[clean_key].append(ref_item)

    # Step B: Process each unique reference name
    for clean_name, records in ref_map.items():
        # Prepare name regex to allow line breaks between words
        name_pattern_str = r'[\s\n]+'.join([re.escape(w) for w in clean_name.split()])
        
        # Find every occurrence of this name in the chapter text
        # Using reversed to avoid offset issues
        matches = list(re.finditer(rf'(?<!\w)({name_pattern_str})(?!\w)(?![^<]*>)', full_text, re.I))
        
        for m in reversed(matches):
            start, end = m.span()
            # Extract the 'local sentence' from the PDF text (approx 200 chars around the match)
            pdf_context = full_text[max(0, start - 150):min(len(full_text), end + 150)].lower()
            
            # Simple keyword-based scoring to find the BEST matching record for THIS instance
            best_id = str(records[0]['_id']) # Default to first record (stringified)
            max_score = -1
            
            for rec in records:
                db_sentence = rec.get('sentence', '').lower()
                # Score = how many words from the DB sentence appear in the PDF context window
                keywords = set(re.findall(r'\w{4,}', db_sentence))
                if not keywords: continue
                
                score = sum(1 for kw in keywords if kw in pdf_context)
                if score > max_score:
                    max_score = score
                    best_id = str(rec['_id']) # Convert ObjectId to HEX string
            
            # Final Highlight Injection
            prefix = full_text[:start]
            suffix = full_text[end:]
            full_text = prefix + f'<span class="hover-ref" data-ref-id="{best_id}">{m.group(1)}</span>' + suffix

    # Section 2: Regulation Highlights (Local Section Refs) - Disabled as requested
    """
    for idx, ref_text in enumerate(cleaned_reg_refs):
        if not isinstance(ref_text, str): continue
        words = ref_text.split()
        if not words: continue
        # Using index as interim ID for regs since they aren't uniquely in a DB collection here
        full_text = pattern.sub(lambda m: get_replacement(m, f"reg_{idx}", "reg"), full_text)
    """

    # 3. Glossary Items
    if search_term != "I":
        for item in glossary_items:
            term = item.get('term', '')
            if not isinstance(term, str) or not term: continue
            t_id = item['_id']
            words = term.split()
            if not words: continue
            
            regex_pattern = r'[\s\n]*'.join([re.escape(w) for w in words])
            pattern = re.compile(rf'\b({regex_pattern}(?:s|es)?)\b(?![^<]*>)', re.IGNORECASE)
                
            full_text = pattern.sub(lambda m: get_replacement(m, t_id, "glossary"), full_text)

    lines = full_text.split("\n")

    def is_header(text):
        clean = re.sub(r'<[^>]+>', '', text).strip().replace("**", "")
        if not clean: return False
        if re.match(r'^(CHAPTER|SCHEDULE|PART|ANNEXURE)\b', clean, re.I): return True
        if clean.isupper() and len(clean) > 10 and not clean.startswith(("(", "SEC", "REG")): return True
        return False

    processed_lines = []
    
    for i, line in enumerate(lines):
        # Use raw text for regex parsing
        stripped_raw = line.replace("**", "").strip()
        stripped_clean = re.sub(r'<[^>]+>', '', stripped_raw)
        
        if not stripped_clean:
            processed_lines.append(line)
            continue

        if re.match(rf'^CHAPTER\s+{re.escape(search_term)}\b', stripped_clean, re.I):
            continue

        if re.match(r'^(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH)\s+SCHEDULE\b', stripped_clean, re.I):
            processed_lines.append('<div class="pdf-page-break"></div>')
            processed_lines.append(f'<div class="sch-header">{line}</div>')
            continue

        if is_header(line):
            # Headers should be clean of highlights
            clean_text = re.sub(r'<[^>]+>', '', line).replace("**", "").strip()
            processed_lines.append(f'# {clean_text}')
            continue

        processed_lines.append(line)

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
    try:
        obj_id = ObjectId(term_id)
        result = collection.find_one({"_id": obj_id})
    except Exception:
        # Fallback for old string IDs if any
        result = collection.find_one({"_id": term_id})
        
    if not result:
        raise HTTPException(status_code=404, detail="Definition not found")
    # Convert ObjectId to string for JSON serialization
    result['_id'] = str(result['_id'])
    return result

@app.get("/api/reference/{ref_id}")
def get_reference_details(ref_id: str):
    # Standard ObjectId lookup
    try:
        obj_id = ObjectId(ref_id)
        result = reference_details_coll.find_one({"_id": obj_id})
    except Exception:
        result = reference_details_coll.find_one({"_id": ref_id})
        
    # FALLBACK: If ID lookup fails, we seek by Name as a safety measure
    if not result:
        # In this scenario, ref_id might be a name if the frontend logic changed
        result = reference_details_coll.find_one({"reference": ref_id})
    
    if not result:
        raise HTTPException(status_code=404, detail="Reference not found")
    
    # Ensure ID and data are JSON-serializable
    result['_id'] = str(result['_id'])
    
    # Critical for Frontend display: Ensure legacy fields exist if missing
    if 'extracted_details' in result:
        # Inject top-level fields for index.html compatibility
        result['extracted_definition'] = result['extracted_details'].get('extracted_definition')
        result['verbatim'] = result['extracted_details'].get('extracted_definition') # Fallback
    
    return result



