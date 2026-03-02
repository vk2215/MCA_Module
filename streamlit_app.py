import html
import json
import os
import re

import streamlit as st
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "compliance_db"
COLLECTION_NAME = "knowledge_base"
ROMAN_ORDER = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "VII": 7,
    "VIII": 8,
    "IX": 9,
    "X": 10,
    "XI": 11,
    "XII": 12,
    "XIII": 13,
    "XIV": 14,
    "XV": 15,
    "XVI": 16,
    "XVII": 17,
    "XVIII": 18,
    "XIX": 19,
    "XX": 20,
}


@st.cache_resource
def get_collection():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    return db[COLLECTION_NAME]


@st.cache_data
def load_raw_data():
    with open("chunks_chapter_wise.json", "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def get_chapters_list():
    chapters = []
    seen = set()
    for chunk in load_raw_data().get("chunks", []):
        metadata = chunk.get("Metadata") or chunk.get("metadata") or {}
        chapter_raw = metadata.get("Chapter") or metadata.get("chapter")
        if not chapter_raw:
            continue
        c_name = str(chapter_raw).replace("**", "").replace("Chapter", "").strip()
        if c_name and c_name not in seen:
            chapters.append(c_name)
            seen.add(c_name)
    def chapter_sort_key(chapter: str):
        normalized = chapter.strip().upper()
        if normalized in ROMAN_ORDER:
            return (0, ROMAN_ORDER[normalized])
        return (1, normalized)

    return sorted(chapters, key=chapter_sort_key)


def build_chapter_content(chapter_name: str):
    content_blocks = []
    search_term = chapter_name.strip()

    for chunk in load_raw_data().get("chunks", []):
        metadata = chunk.get("Metadata") or chunk.get("metadata") or {}
        raw_val = str(metadata.get("Chapter") or metadata.get("chapter", ""))
        clean_val = raw_val.replace("**", "").replace("Chapter", "").strip()
        if clean_val == search_term:
            content_blocks.append(chunk.get("Content", ""))

    if not content_blocks:
        return None

    full_text = "\n\n".join(content_blocks)
    lines = full_text.split("\n")

    repaired_lines = []
    for i, current_line in enumerate(lines):
        repaired_lines.append(current_line)
        if current_line.strip().startswith("|") and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line and not next_line.startswith("|"):
                repaired_lines.append("")

    lines = repaired_lines

    if "|" in full_text and "|---" not in full_text:
        for i, line in enumerate(lines):
            if "|" in line and i + 1 < len(lines) and "|" in lines[i + 1]:
                cols = line.count("|") - 1
                lines.insert(i + 1, "|" + "---|" * cols)
                break

    if search_term != "I":
        glossary_items = list(get_collection().find({}, {"_id": 1, "term": 1}))
        glossary_items.sort(key=lambda x: len(x["term"]), reverse=True)
        final_lines = []
        for line in lines:
            if line.strip().startswith("|"):
                final_lines.append(line)
                continue
            for item in glossary_items:
                term = item["term"]
                t_id = item["_id"]
                pattern = re.compile(rf"\b({re.escape(term)})\b", re.IGNORECASE)
                line = pattern.sub(
                    f'<span class="hover-term" data-id="{t_id}">\\1</span>', line
                )
            final_lines.append(line)
        full_text = "\n".join(final_lines)
    else:
        full_text = "\n".join(lines)

    return full_text


@st.cache_data
def get_definitions_map():
    docs = get_collection().find({}, {"_id": 1, "term": 1, "verbatim": 1})
    return {str(d["_id"]): d for d in docs}


def add_tooltip_title(text: str):
    defs = get_definitions_map()

    def repl(match):
        term_id = match.group(1)
        term_text = match.group(2)
        doc = defs.get(term_id)
        if not doc:
            return term_text
        tooltip = doc.get("verbatim", "").replace("\n", " ")
        tooltip = re.sub(r"\s+", " ", tooltip).strip()
        tooltip = html.escape(tooltip, quote=True)
        return f'<span class="hover-term" title="{tooltip}">{term_text}</span>'

    pattern = re.compile(r'<span class="hover-term" data-id="([^"]+)">(.*?)</span>')
    return pattern.sub(repl, text)


st.set_page_config(page_title="Compliance Portal", layout="wide")

query_params = st.query_params

st.markdown(
    """
<style>
        :root {
            --bg: #ffffff;
            --sidebar: #0f172a;
            --paper-bg: #ffffff;
            --accent: #2563eb;
            --font-body: 'Times New Roman', Times, serif;
            --font-ui: 'Inter', sans-serif;
        }

        body {
            margin: 0;
            display: flex;
            height: 100vh;
            background: var(--bg);
            font-family: var(--font-ui);
        }

        #sidebar {
            width: 260px;
            background: var(--sidebar);
            color: white;
            height: 100vh;
            position: fixed;
            overflow-y: auto;
        }

        #sidebar h2 {
            padding: 20px;
            font-size: 1.1rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            border-bottom: 1px solid #1e293b;
        }

        .chap-item {
            padding: 12px 20px;
            cursor: pointer;
            transition: all 0.2s;
            color: #cbd5e1;
            border-bottom: 1px solid #1e293b;
        }

        .chap-item:hover {
            background: #1e293b;
            color: white;
        }

        #main {
            margin-left: 260px;
            padding: 40px;
            flex: 1;
            overflow-y: auto;
        }

        /* Gazette Style Paper */
        .paper {
            background: var(--paper-bg);
            padding: 60px 80px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
            max-width: 900px;
            margin: 0 auto;
            font-family: var(--font-body);
            font-size: 12pt;
            line-height: 1.5;
            color: #000;
        }

        /* Legal Alignment Grid (Flexbox) */
        .reg-row {
            display: flex;
            align-items: flex-start;
            margin-bottom: 10px;
            text-align: justify;
        }

        .marker {
            flex-shrink: 0;
            min-width: 45px; /* Adjust gutter width */
            font-weight: normal;
        }

        .content {
            flex-grow: 1;
        }

        /* Precise Indentation Levels */
        .reg-level-1 { margin-left: 0px; }
        .reg-level-2 { margin-left: 45px; } 
        .reg-level-3 { margin-left: 90px; }

        /* Headers */
        h1 { text-align: center; text-transform: uppercase; font-size: 1.4rem; margin-bottom: 30px; }
        h2 { text-align: center; text-transform: uppercase; font-size: 1.2rem; margin-top: 40px; }

        /* PDF Style Tables */
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            table-layout: auto;
        }

        th, td {
            border: 1px solid #000 !important;
            padding: 8px;
            text-align: left;
            vertical-align: top;
            font-size: 11pt;
        }

        th { background: #f8fafc; font-weight: bold; }

        /* Persistent Blue Underline for Terms */
        .hover-term {
            color: var(--accent);
            font-weight: 600;
            text-decoration: underline solid var(--accent) !important;
            cursor: help;
        }

        .hover-term:hover { background: #eff6ff; }

        /* Tippy Styling */
        .nested-pt {
            display: block;
            margin-top: 5px;
            padding-left: 10px;
            border-left: 2px solid var(--accent);
        }
    </style>
""",
    unsafe_allow_html=True,
)

st.sidebar.markdown("## REGULATIONS")
chapters = get_chapters_list()

if not chapters:
    st.error("No chapter data found in chunks_chapter_wise.json")
    st.stop()

default_chapter = "I" if "I" in chapters else chapters[0]
selected = query_params.get("chapter", default_chapter)
if selected not in chapters:
    selected = default_chapter

links = []
for chapter in chapters:
    active_class = "chap-link-active" if chapter == selected else ""
    links.append(
        f'<li><a class="{active_class}" href="?chapter={chapter}">Chapter {chapter}</a></li>'
    )

st.sidebar.markdown(f"<ul>{''.join(links)}</ul>", unsafe_allow_html=True)

raw_content = build_chapter_content(selected)
if not raw_content:
    st.error(f"Chapter {selected} not found")
    st.stop()

content_with_tooltips = add_tooltip_title(raw_content)
content = f"## Chapter {selected}\n\n{content_with_tooltips}"

st.markdown('<div class="paper">', unsafe_allow_html=True)
st.markdown(content, unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)
