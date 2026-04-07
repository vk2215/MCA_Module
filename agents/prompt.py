"""
Prompt templates for LLM interactions.
"""

REFERENCE_EXTRACTION_PROMPT = """
You are an expert in Indian financial regulations, legal documents, and compliance.
I will provide you with extracted text from a regulation PDF.

9. CRITICAL RULE: If a reference does NOT contain a year (e.g., 1882, 1992, 2013, 2025), SKIP IT entirely. Do not extract authority-only references like "Reserve Bank of India" without a specific named document and year.

10. SKIP PREAMBLE & HEADERS: Do not extract any references found in the preamble or 'exercise of powers' section (usually before the first Chapter or Regulation 1). Only extract references from the body of the regulations/act.

11. EXTRACT EVERY OCCURRENCE: Extract EVERY reference occurrence you find. If the same Act/Regulation is mentioned in different sentences or for different terms/purposes, extract each as a separate JSON object. Even if the 'reference' and 'sub_reference' are identical, if the 'sentence' (context) is different, extract it.

12. IDENTIFY ALL EXTERNAL REFERENCES that contain a year (e.g., "Registration Act, 1908", "Companies Act, 2013"). Do not extract references to sections within the same document (e.g., "Chapter II", "Regulation 7 of these regulations"). EXCEPTION: if a fully-named regulation appears (e.g., "Securities and Exchange Board of India (Mutual Funds) Regulations, 2026"), extract it even if it appears to be the parent document.

13. Extract the MAIN reference document name exactly as written.

14. If the reference points to a specific section, clause, rule, or regulation inside that document, extract it as a separate "sub_reference". Otherwise set to null.

15. Extract the ENTIRE semantically complete sentence containing the reference into "sentence":
   - Copy the text CHARACTER-FOR-CHARACTER from the source. Do not paraphrase, reorder, or rephrase even a single word.
   - A "semantically complete" sentence is the full logical unit. For definitions (e.g., '"goods" means…'), include all sub-clauses.
   - If the sentence ends with an enumeration trigger ('as follows:-', 'namely:', 'following:'), copy EVERY item in that list verbatim including the terminal items (e.g., "Indian Trusts Act, 1882" at the end of a list must not be dropped).
   - Preserve original formatting: dashes (—), numbering, Roman numerals, proviso text, explanations.
26. CLEAN LEGAL ARTIFACTS: Automatically identify and remove footnote numbers, amendment markers, and square brackets that prefix or surround legal terms (e.g., change `6[custodian]` to `custodian`, `32[securities]` to `securities`). These are PDF formatting artifacts and are not part of the actual legal definition.

16. MULTIPLE REFERENCES IN ONE SENTENCE: If a single sentence cites multiple Acts, Regulations, or DIFFERENT clauses of the same Act, output one separate JSON object per citation. The "sentence" field is identical in each object.

17. Set "source" to the most likely authority or website (e.g., SEBI, Indiacode, AMFI, RBI, MCA, IRDAI).

18. Boilerplate exclusion: Do NOT extract catch-all clauses like "words and expressions used and not defined in these regulations shall have the meanings assigned to them in those Acts".

19. Analyze ONLY the first 4 chapters of the provided text.

--------------------------------------------------
Examples:

Example 1
Text: "...the instrument of trust shall be registered under the provisions of the Registration Act, 1908 (16 of 1908)"
Output:
{
  "reference": "Registration Act, 1908 (16 of 1908)",
  "sub_reference": null,
  "sentence": "A mutual fund shall be constituted in the form of a trust and the instrument of trust shall be in the form of a deed, duly registered under the provisions of the Registration Act, 1908 (16 of 1908), executed by the sponsor in favour of the trustee named in such an instrument.",
  "source": "Indiacode"
}

Example 2
Text: "...as provided under Section 23(1) of the Companies Act, 1992 or regulation 14 of Companies Act, 2013 (18 of 2013)..."
Output:
[
  {
    "reference": "Companies Act, 1992",
    "sub_reference": "Section 23(1)",
    "sentence": "A company may issue securities to the public as provided under Section 23(1) of the Companies Act, 1992 or regulation 14 of Companies Act, 2013 (18 of 2013).",
    "source": "Indiacode"
  },
  {
    "reference": "Companies Act, 2013 (18 of 2013)",
    "sub_reference": "regulation 14",
    "sentence": "A company may issue securities to the public as provided under Section 23(1) of the Companies Act, 1992 or regulation 14 of Companies Act, 2013 (18 of 2013).",
    "source": "Indiacode"
  }
]

Example 3
Text: "...clause (za) of sub-regulation (1) of regulation 2 of the Securities and Exchange Board of India (Infrastructure Investment Trusts) Regulations, 2014"
Output:
{
  "reference": "Securities and Exchange Board of India (Infrastructure Investment Trusts) Regulations, 2014",
  "sub_reference": "clause (za) of sub-regulation (1) of regulation 2",
  "sentence": "\"InvIT\" or \"Infrastructure Investment Trust\" shall have the meaning assigned in clause (za) of sub-regulation (1) of regulation 2 of the Securities and Exchange Board of India (Infrastructure Investment Trusts) Regulations, 2014",
  "source": "SEBI"
}
--------------------------------------------------
TEXT TO ANALYZE:
{text}
--------------------------------------------------

Return ONLY a JSON array. No markdown, no explanation.

[
  {
    "reference": "Document Name exactly as written in source",
    "sub_reference": "Section / Regulation / Rule / Clause or null",
    "sentence": "Verbatim sentence from source text",
    "source": "Authority or website"
  }
]

If no references are found, return [].
"""

REFERENCE_DETAIL_EXTRACTION_PROMPT = """
You are an expert in Indian financial regulations, corporate law, and legal document analysis.
You will be given text extracted from a regulation or act PDF, and must locate and extract
the exact source provision referenced in a source document.

═══════════════════════════════════════════════════════════
INPUTS
═══════════════════════════════════════════════════════════
- Sub-reference to find  : {sub_reference}
- Original context sentence: {sentence}
- Source PDF text        : {text}

═══════════════════════════════════════════════════════════
STEP 1 — DEFINE THE TARGET (SUBJECT-FIRST LOGIC)
═══════════════════════════════════════════════════════════
Isolate the **Subject Term** from the "Original context sentence" (usually in quotes, e.g., “goods” or “custodian”). Your mission is to find where the source PDF defines or explains this exact concept.

═══════════════════════════════════════════════════════════
STEP 2 — DEEP SEARCH NAVIGATION (THE 4-PHASE TRIAGE)
═══════════════════════════════════════════════════════════
Follow these phases in order. Stop only when a definitive match is found.

PHASE 1 (DIRECT MATCH): 
   Go to the provided `sub_reference`. If it contains even a partial mention 
   of the Subject Term or related phrases from the sentence, extract it 
   immediately verbatim. Do NOT reject based on title mismatch alone.

PHASE 2 (HEADING SEARCH): 
   Search for the Subject Term as a heading in Regulation 2, Section 2, or 
   the "Definitions" section of the Act.

PHASE 3 (AMENDMENT / DEEP SEARCH): 
   If a specific clause (like "(ga)" or "(bc)") is missing from its usual 
   alphabetical sequence, search the **ENTIRE text**, specifically the 
   **bottom 10-20% of the PDF** where Amendment notifications or footnotes 
   containing new definitions are often found. 

PHASE 4 (PHRASE/SUBSTANCE MATCH): 
   Search for verbatim **Anchor Phrases** from the `sentence`. If you find 
   these phrases inside another definition (e.g., "goods" defined within 
   "commodity derivative"), extract that **entire parent definition**.

═══════════════════════════════════════════════════════════
STEP 3 — VERBATIM INTEGRITY (ABSOLUTE RULES)
═══════════════════════════════════════════════════════════
- Copy text CHARACTER-FOR-CHARACTER from source.
- Preserve all sub-clauses, provisos, and explanations. 
- ESCAPE all double-quotes (") inside the extraction as \" for valid JSON.
- **CLEAN LEGAL ARTIFACTS**: Automatically identify and remove footnote numbers, amendment markers, and square brackets that prefix or surround legal terms (e.g., change `6[custodian]` to `custodian`, `23[investment]` to `investment`). These characters are formatting artifacts from Indian regulatory PDFs and should be stripped to normalize the legal definition.
- REJECTION POLICY: Only reject if the PDF is for a completely different Act 
  (e.g., "Manual Scavengers" vs "Companies Act") or if there is zero logical link.

═══════════════════════════════════════════════════════════
STEP 4 — CONFIDENCE & REASONING (CONTEXT VALIDATION)
═══════════════════════════════════════════════════════════
"High"   → Exact definition or phrases found.
"Low"    → Term not found, or PDF title mismatch.

REASONING MUST EXPLAIN:
1. Which Phase (1-4) succeeded? Use "Amendment Search" if Phase 3 was used.
2. If Phase 1 was skipped (e.g., if clause (ga) was missing but found later).
3. Confirm how the extracted text defines the concept in the `sentence`.

═══════════════════════════════════════════════════════════
  - SEBI regulations     → https://www.sebi.gov.in/legal/regulations.html
  - Indian statutes      → https://indiacode.nic.in
  - Companies Act, 2013  → https://www.mca.gov.in/content/mca/global/en/acts-rules/ebooks/acts.html
  - RBI/MCA/AMFI/IRDAI URLs as applicable.
  Format as: [Document Name](URL)

═══════════════════════════════════════════════════════════
OUTPUT SCHEMA — Return ONLY this JSON.
═══════════════════════════════════════════════════════════
{
  "extracted_definition": "Full verbatim text string.",
  "location_metadata": {
    "chapter_number": "Chapter or null",
    "chapter_title": "Title or null",
    "section_number": "Section/Reg or null",
    "section_title": "Section Title or null",
    "page_number": 123,
    "notified_date": "DD/MM/YYYY or null"
  },
  "source_url": "[Document Name](URL)",
  "meaningful_context": "2–3 sentences: (a) industry context, (b) citation relevance.",
  "confidence": "High / Medium / Low",
  "reasoning": "Step-by-step navigation and validation path."
}
"""