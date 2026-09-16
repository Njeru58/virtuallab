NUM_QUESTIONS_PER_TEST = 5
RATING_INCREMENT = 0.10
RATING_DECREMENT = 0.05
MAX_RATING = 5.00
MIN_RATING = 0.00
from google import genai
import google.generativeai as genai
import logging
import json
logger = logging.getLogger(__name__)
from .models import ExpectedMeasurement
# ---------- INLINE CONSTANTS ---------- #
MIN_WORDS_PER_SECTION = 3

LAB_RUBRIC = {
    "objective": 10,
    "theory": 15,
    "apparatus_scope": 5,
    "procedure": 8,
    "results": 5,        # narrative + structured JSON table
    "data_analysis": 25,
    "discussion": 20,
    "conclusion": 15,
    "references": 2,
}
# -------------------------------------- #
def merge_data_analysis(report):
    """
    Combine data analysis equations, error analysis, and tables
    for AI evaluation.
    """
    text = report.data_analysis or ""
    if getattr(report, "error_analysis", None):
        text += f"\n\n[Error Analysis]\n{report.error_analysis}"

    if getattr(report, "experimental_tables", None):
        try:
            import pandas as pd
            tables = report.experimental_tables
            if isinstance(tables, str):
                tables = json.loads(tables)
            for i, t in enumerate(tables, 1):
                df = pd.DataFrame(t)
                text += f"\n\n[Experimental Table {i}]\n{df.to_markdown(index=False)}"
        except Exception as e:
            text += f"\n\n[Table Error] {e}"
    return text


import re 
import difflib 
from difflib import SequenceMatcher

APPARATUS_ALIASES = {
    # Core canonical mappings (aliases → canonical)
    "meter rule": "metre rule",
    "ruler": "metre rule",
    "micrometer": "micrometer screw gauge",
    "micrometer screw gauges": "micrometer screw gauge",
    "screw gauge": "micrometer screw gauge",
    "vernier": "vernier calipers",
    "vernier caliper": "vernier calipers",
    "vernier scale": "vernier calipers",
    "weighing balance": "electronic balance",
    "balance": "electronic balance",
    "graduated cylinder": "measuring cylinder",
    "measuring cylinder": "measuring cylinder",
    "wire": "copper wire",

    "vernier callipers": "vernier calipers",
    "micrometre screwgauge": "micrometer screw gauge",
    "capplilary tube": "capillary tube",


    # Self-maps (so canonical terms always match themselves)
    "metre rule": "metre rule",
    "micrometer screw gauge": "micrometer screw gauge",
    "vernier calipers": "vernier calipers",
    "electronic balance": "electronic balance",
    "measuring cylinder": "measuring cylinder",
    "copper wire": "copper wire",

    # Common lab tools (optional, for robustness)
    "test tube": "test tube",
    "thermometer": "thermometer",
    "burette": "burette",
    "pipette": "pipette",
    "conical flask": "conical flask",
    "beaker": "beaker",
    "stopwatch": "stopwatch",
    "spring balance": "spring balance",
}



# Build canonical → variant list mapping
CANONICAL_VARIANTS = {}

for alias, canonical in APPARATUS_ALIASES.items():
    alias = alias.lower()
    canonical = canonical.lower()
    CANONICAL_VARIANTS.setdefault(canonical, set()).add(alias)
    CANONICAL_VARIANTS[canonical].add(canonical)  # ensure self included

# Convert sets to lists
for k in CANONICAL_VARIANTS:
    CANONICAL_VARIANTS[k] = list(CANONICAL_VARIANTS[k])


import re
from difflib import SequenceMatcher
from nltk.stem import PorterStemmer
import re
from nltk.stem import PorterStemmer

# --------------------------
# Synonyms, generic words, and bonus keywords
# --------------------------
GENERIC_WORDS = {"wire", "copper", "glass", "tube", "cylinder", "apparatus", "rule", "meter"}
SYNONYMS = {
    "study": ["learn", "get familiar with", "investigate"],
    "compute": ["determine", "calculate", "measure"],
    "instruments": ["tools", "apparatus"],
    "precision measurements": ["accuracy of tools", "precise instruments"],
    "objects": ["items", "samples"],
}
BONUS_KEYWORDS = {"instrument", "instruments", "accuracy", "error", "errors", "measurement", "measurements"}

stemmer = PorterStemmer()

# --------------------------
# Helper functions
# --------------------------
def tokenize_and_stem(text):
    """Return a set of stemmed words from text, ignoring short words."""
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    return {stemmer.stem(w) for w in words if len(w) > 2}

def expand_synonyms(keywords):
    """Expand keywords with known synonyms."""
    expanded = set(keywords)
    for kw in keywords:
        if kw in SYNONYMS:
            expanded.update(SYNONYMS[kw])
    return expanded

def normalize_text(text):
    """Lowercase, remove punctuation, and collapse spaces."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return " ".join(text.split())

# --------------------------
# Main objective evaluator
# --------------------------
def evaluate_objective(report, experiment):
    """
    Evaluates a student's objective fairly using stemmed keywords + synonyms.
    Ignores minor rephrasing or word order differences.
    """

    student_obj = getattr(report, "objective", "") or ""
    ref_obj = getattr(experiment, "objective", "") or ""

    if not student_obj:
        return {"rubric": 0, "feedback": "Objective section missing."}
    if not ref_obj:
        return {"rubric": 0, "feedback": "Reference objective missing."}

    # Remove common starting phrases
    for prefix in [
        r'the purpose of this experiment is to',
        r'this experiment aims to',
        r'we are going to',
        r'to'
    ]:
        student_obj = re.sub(fr'^{prefix}\s+', '', student_obj, flags=re.I)
        ref_obj = re.sub(fr'^{prefix}\s+', '', ref_obj, flags=re.I)


    # Normalize, tokenize, stem
    student_tokens = expand_synonyms(tokenize_and_stem(normalize_text(student_obj)))
    ref_tokens = expand_synonyms(tokenize_and_stem(normalize_text(ref_obj)))

    # Remove generic words that shouldn't penalize the student
    student_tokens -= GENERIC_WORDS
    ref_tokens -= GENERIC_WORDS

    # Keyword overlap (main scoring)
    overlap = student_tokens & ref_tokens
    keyword_overlap = len(overlap) / max(len(ref_tokens), 1)

    # Fuzzy sequence similarity (minor weighting)
    from difflib import SequenceMatcher
    seq_ratio = SequenceMatcher(None, normalize_text(student_obj), normalize_text(ref_obj)).ratio()

    # Weighted combination: prioritize keywords heavily
    combined_score = 0.75 * keyword_overlap + 0.25 * seq_ratio  # slightly more weight to fuzzy match
    rubric = round(min(combined_score * 10, 10), 1)

    # Soft minimum credit: give a small boost for partial overlap
    if keyword_overlap >= 0.5 and rubric < 7:
        rubric = max(rubric, 7.0)
    elif keyword_overlap >= 0.25 and rubric < 5:   # lowered threshold from 0.3 -> 0.25
        rubric = max(rubric, 5.5)                 # boost baseline to 5.5

    # Feedback
    if rubric >= 9:
        feedback = "Objective perfectly aligns with the aim of the experiment."
    elif rubric >= 7:
        feedback = "Objective aligns well with the aim of the experiment."
    elif rubric >= 5:
        feedback = "Objective is relevant and mostly complete; minor improvements possible."
    elif rubric >= 3:
        feedback = "Objective shows understanding but could be expressed more clearly."
    else:
        feedback = "Objective does not sufficiently align with the aim of this experiment."

    return {"rubric": rubric, "feedback": feedback}





def extract_instruments_from_text(ref_text: str, apparatus_list: list[str]) -> list[str]:
    """
    Extracts only those apparatus names that actually appear in the reference theory text.
    This prevents penalizing students for omitting unrelated instruments.
    """
    found = []
    ref_text = normalize_text(ref_text)
    for item in apparatus_list:
            variants = APPARATUS_ALIASES.get(item, [item]) if isinstance(APPARATUS_ALIASES.get(item, None), list) else [APPARATUS_ALIASES.get(item, item)]
            if any(v in ref_text for v in variants):
                found.append(item)

    return list(set(found))


def evaluate_theory(report, experiment):
    """
    Kamui Engine — Advanced schema-based evaluation of Theory section.
    Evaluates:
    - Conceptual relevance (keywords and context)
    - Relation to experiment title
    - Instrument coverage
    - Structure and figures
    - Bloom’s cognitive level (recall → application)

    Returns: { "rubric": float(0–10), "feedback": str }
    """
    import re
    from difflib import SequenceMatcher
    from collections import Counter

    student_text = normalize_text(getattr(report, "theory", "") or "")
    ref_text = normalize_text(experiment.theory or "")

    if not student_text or not ref_text:
        return {"rubric": 0, "feedback": "Theory section missing or empty."}

    # --- 1️⃣ Auto-Build Schema from Reference Theory ---
    ref_tokens = ref_text.split()
    # extract key nouns, verbs, and scientific terms (simple heuristic)
    keywords = [w for w in ref_tokens if len(w) > 4 and not w.isdigit()]
    key_concepts = list(set(keywords))[:50]  # trim to avoid noise

    # Extract known instruments
    # ✅ Extract apparatus list and limit expected ones to those actually used in the reference theory
    all_instruments = [normalize_text(a.name) for a in experiment.apparatus_items.all()]
    reference_instruments = extract_instruments_from_text(ref_text, all_instruments)
    if not reference_instruments:
        reference_instruments = all_instruments  # fallback if theory text doesn’t mention them


    # Extract figure mentions
    figure_refs = re.findall(r'figure\s*\d+(\.\d+)?', ref_text)

    # --- 2️⃣ Cross-check Schema in Student Theory ---
    student_tokens = set(student_text.split())

    # Concept match (fuzzy overlap)
    matched_concepts = [
        k for k in key_concepts
        if any(fuzzy_match(k, s) for s in student_tokens)
    ]
    concept_coverage = len(matched_concepts) / max(1, len(key_concepts))

    # Instrument coverage
    # ✅ Match only reference instruments; reward extra valid mentions
    matched_instruments = [
        i for i in reference_instruments
        if i in student_text or fuzzy_match(i, student_text)
    ]

    instrument_coverage = len(matched_instruments) / max(1, len(reference_instruments))
    missing_instruments = set(reference_instruments) - set(matched_instruments)

    # Bonus credit for mentioning valid extras beyond reference theory
    extra_instruments = [
        i for i in all_instruments
        if i not in reference_instruments and (i in student_text or fuzzy_match(i, student_text))
    ]
    bonus_score = min(len(extra_instruments) * 0.05, 0.15)


    # Figure acknowledgment
    student_figures = re.findall(r'figure\s*\d+(\.\d+)?', student_text)
    figure_score = min(len(student_figures) / max(1, len(figure_refs)), 1.0)

    # --- 3️⃣ Title Relevance ---
    title_keywords = set(normalize_text(experiment.title).split())
    relevance = len([t for t in title_keywords if t in student_text]) / max(1, len(title_keywords))

    # --- 4️⃣ Bloom’s Level Heuristic ---
    higher_order_terms = ["derive", "explain", "relate", "calculate", "apply", "interpret", "compare"]
    lower_order_terms = ["define", "know", "learn", "state", "understand"]
    bloom_terms = Counter({"high": 0, "low": 0})

    for w in student_text.split():
        if w in higher_order_terms: bloom_terms["high"] += 1
        if w in lower_order_terms: bloom_terms["low"] += 1

    bloom_ratio = bloom_terms["high"] - bloom_terms["low"]
    bloom_score = max(min((bloom_ratio + 1) / 2, 1), 0)

    # --- 5️⃣ Weighted Score Assembly ---
    rubric = (
        concept_coverage * 0.4 +
        (instrument_coverage + bonus_score) * 0.25 +
        relevance * 0.1 +
        figure_score * 0.1 +
        bloom_score * 0.15
    ) * 10

    rubric = round(min(rubric, 10), 1)

    # --- 6️⃣ Feedback Construction ---
    feedback = []

    # Conceptual
    if concept_coverage < 0.4:
        feedback.append("Key theoretical concepts are missing or insufficiently covered.")
    elif concept_coverage < 0.7:
        feedback.append("Covers main ideas but misses depth in explanation.")
    else:
        feedback.append("Conceptual understanding is well demonstrated.")

    # Instruments
    if instrument_coverage < 0.5:
        feedback.append(f"Core instruments from the theory are missing: {', '.join(missing_instruments)}.")
    elif bonus_score > 0:
        feedback.append("Core instruments covered, with extra relevant ones mentioned — great detail.")
    else:
        feedback.append("Instruments are well identified and aligned with the reference theory.")

    # Figures
    if figure_refs and not student_figures:
        feedback.append("Figures or diagrams mentioned in the experiment are not acknowledged.")
    elif student_figures:
        feedback.append("References to figures are present, showing structural completeness.")

    # Title relevance
    if relevance < 0.5:
        feedback.append("Theory weakly relates to the experiment title or context.")
    else:
        feedback.append("Theory is relevant to the experiment's purpose.")

    # Bloom’s reasoning
    if bloom_score < 0.3:
        feedback.append("Explanation remains descriptive; lacks analysis or interpretation.")
    elif bloom_score > 0.7:
        feedback.append("Shows analytical and application-level reasoning.")

    # Join
    feedback_text = " ".join(feedback)

    return {"rubric": rubric, "feedback": feedback_text}


def fuzzy_match(a: str, b: str, threshold: float = 0.8) -> bool:
    """Approximate similarity for close spellings."""
    return SequenceMatcher(None, a, b).ratio() >= threshold


def evaluate_apparatus_scope(report, experiment):
    """Evaluates student's apparatus list with refined semantic matching."""
    student_text = normalize_text(getattr(report, "apparatus_scope", ""))
    reference_items = [normalize_text(a.name) for a in experiment.apparatus_items.all()]

    if not student_text or not reference_items:
        return {
            "rubric": 0,
            "feedback": "<p><i class='fa fa-exclamation-circle text-danger'></i> "
                        "Missing apparatus section or no reference items defined.</p>",
            "coverage_percent": 0,
            "matched": [],
            "missing": reference_items,
        }

    matched, missing, alias_hits = [], reference_items.copy(), []
    student_items = [normalize_text(t) for t in re.split(r'[\n,;]+', student_text) if t.strip()]

    for ref in reference_items:
        ref_tokens = ref.split()
        ref_clean = " ".join(ref_tokens)

        # 1️⃣ Direct or alias-based normalization
        canonical = APPARATUS_ALIASES.get(ref_clean, ref_clean)
        if isinstance(canonical, list):
            ref_tokens = [w for c in canonical for w in c.split()]
        else:
            ref_tokens = canonical.split()


        for student_item in student_items:
            item_tokens = student_item.split()

            # 🔹 NEW: Direct substring check for full instrument name (prevents partial double-counts)
            if isinstance(canonical, list):
                # canonical is a list of alias variants like ["micrometer", "screw gauge"]
                if any(alias in student_item for alias in canonical):
                    matched.extend(canonical)  # record all recognized aliases
                    for alias in canonical:
                        if alias in missing:
                            missing.remove(alias)
                    continue  # skip further matching
            else:
                # canonical is a single instrument name
                if canonical in student_item:
                    matched.append(canonical)
                    if canonical in missing:
                        missing.remove(canonical)
                    continue  # skip further token/fuzzy matching for this item

            # Skip matches only based on generic materials
            overlap = [t for t in ref_tokens if t in item_tokens and t not in GENERIC_WORDS]
            token_match_ratio = len(overlap) / len(ref_tokens)

            # 2️⃣ Require at least 1 non-generic word + 70% overlap
            if overlap and token_match_ratio >= 0.7:
                matched.append(canonical)
                if canonical in missing:
                    missing.remove(canonical)
                break

            # 3️⃣ Fuzzy fallback (for small text differences)
            if fuzzy_match(student_item, canonical):
                matched.append(canonical)
                if canonical in missing:
                    missing.remove(canonical)
                break

            # 4️⃣ Explicit alias hits
            for alias, canonical_ref in APPARATUS_ALIASES.items():
                if alias in student_item and canonical_ref == canonical:
                    alias_hits.append((alias, canonical_ref))
                    matched.append(canonical_ref)
                    if canonical_ref in missing:
                        missing.remove(canonical_ref)
                    break

    # ✅ Flatten nested lists before computing coverage
    flatten = lambda seq: [item for sub in seq for item in (sub if isinstance(sub, list) else [sub])]
    matched = flatten(matched)
    reference_items = flatten(reference_items)

    coverage = (len(set(matched)) / len(set(reference_items))) * 100

    rubric_score = round((coverage / 100) * 10, 1)

    # ✅ Simplified and clearer feedback
    feedback_lines = [
        f"Apparatus coverage: {coverage:.1f}% ({rubric_score}/10)"
    ]

    if matched:
        feedback_lines.append(f"Matched: {', '.join(sorted(set(matched)))}")

    if alias_hits:
        alias_info = ', '.join([f"{s} → {r}" for s, r in alias_hits])
        feedback_lines.append(f"Aliases recognized: {alias_info}")

    if missing:
        feedback_lines.append(f"Missing or unclear: {', '.join(sorted(set(missing)))}")

    feedback_lines.append(
        "Tip: Ensure all required instruments are clearly listed using standard lab names."
    )

    # Join each insight into a readable multi-line feedback block
    feedback = "<br>".join(feedback_lines)

    return {
        "rubric": rubric_score,
        "feedback": feedback,
        "coverage_percent": round(coverage, 1),
        "matched": matched,
        "missing": missing,
    }

from difflib import SequenceMatcher

from fuzzywuzzy import fuzz
import re

# ✅ ADD THIS LAZY-LOADER FOR SPA CY
_nlp_model = None

def get_nlp_model():
    global _nlp_model
    if _nlp_model is None:
        import spacy
        _nlp_model = spacy.load("en_core_web_sm")
    return _nlp_model


# -----------------------------
# 2️⃣ Build Schema from Reference
# -----------------------------
def build_procedure_schema(reference_steps):
    """
    Build schema with extracted keywords per reference step.
    """
    instruments = ["meter rule", "micrometer", "screw gauge", "balance", "vernier", "caliper"]
    verbs = ["measure", "record", "use", "determine", "observe", "weigh", "note"]
    targets = ["length", "diameter", "mass", "zero", "reading", "error"]

    schema = []
    for step in reference_steps:
        s = step.lower()
        keywords = []

        for term in instruments + verbs + targets:
            if term in s:
                keywords.append(term)

        schema.append({
            "step": step,
            "keywords": list(set(keywords))
        })

    return schema

# -----------------------------
# 3️⃣ Schema-based Matching
# -----------------------------
def evaluate_procedure_schema(student_text, reference_steps):
    """
    Schema-based matching with partial credit and keyword feedback.
    """
    schema = build_procedure_schema(reference_steps)
    student_text = student_text.lower()

    matched_steps = []
    missing_steps = []
    keyword_feedback = []

    total_ratio = 0

    for item in schema:
        found = [kw for kw in item["keywords"] if kw in student_text]
        missing = [kw for kw in item["keywords"] if kw not in student_text]
        ratio = len(found) / max(1, len(item["keywords"]))
        total_ratio += ratio

        if ratio >= 0.6:
            matched_steps.append(item["step"])
        else:
            missing_steps.append(item["step"])

        keyword_feedback.append({
            "step": item["step"],
            "found_keywords": found,
            "missing_keywords": missing,
            "match_ratio": round(ratio, 2)
        })

    coverage_percent = (total_ratio / len(schema)) * 100 if schema else 0
    return coverage_percent, matched_steps, missing_steps, keyword_feedback

# -----------------------------
# 4️⃣ Tense Detection
# -----------------------------
def detect_procedure_tense(student_text: str):
    nlp = get_nlp_model()  # <--- CHANGED
    doc = nlp(student_text)
    issues = []

    for sent in doc.sents:
        wrong_tense = False
        for token in sent:
            if token.pos_ == "VERB" and token.tag_ not in {"VBD", "VBN"}:
                wrong_tense = True
                break
        if wrong_tense:
            issues.append(sent.text)

    tense_penalty = min(len(issues) * 0.05, 0.2)
    return tense_penalty, issues

# -----------------------------
# 6️⃣ Irrelevant Sentence Detection
# -----------------------------
def detect_irrelevant_sentences(student_text: str, schema_keywords, threshold=0.3, max_penalty=0.15):
    nlp = get_nlp_model()  # <--- CHANGED
    doc = nlp(student_text)
    irrelevant = []
    total_words = sum(len(sent.text.split()) for sent in doc.sents) or 1  # avoid division by zero
    weighted_penalty = 0

    for sent in doc.sents:
        sent_text = sent.text.lower()
        max_overlap_ratio = 0

        for step in schema_keywords:
            step_keywords = set(step["keywords"])
            if not step_keywords:
                continue
            matched_keywords = [kw for kw in step_keywords if kw in sent_text]
            overlap_ratio = len(matched_keywords) / len(step_keywords)
            max_overlap_ratio = max(max_overlap_ratio, overlap_ratio)

        if max_overlap_ratio < threshold:
            irrelevant.append(sent.text.strip())
            # Weight by fraction of total words
            sent_weight = len(sent.text.split()) / total_words
            weighted_penalty += sent_weight * max_penalty

    # Cap the penalty at max_penalty
    penalty = min(weighted_penalty, max_penalty)
    return penalty, irrelevant



# -----------------------------
# 5️⃣ Final Procedure Evaluation
# -----------------------------
def evaluate_procedure(report, experiment):
    """
    Evaluate procedure section:
    - Keyword schema coverage (partial credit)
    - Tense correctness
    - Irrelevant sentence detection
    """
    student_text = getattr(report, "procedure", "") or ""
    reference_steps = [s.instruction for s in experiment.experimentstep_set.all()]

    # Step coverage
    coverage_percent, matched_steps, missing_steps, keyword_feedback = evaluate_procedure_schema(student_text, reference_steps)


    tense_penalty, tense_issues = detect_procedure_tense(student_text)

    schema = build_procedure_schema(reference_steps)
    irrelevant_penalty, irrelevant_sentences = detect_irrelevant_sentences(student_text, schema)

    APPLY_TENSE_PENALTY = True
    total_penalty = (tense_penalty + irrelevant_penalty) * 10 if APPLY_TENSE_PENALTY else 0

    rubric = round((coverage_percent / 100) * 10 - total_penalty, 1)
    rubric = max(0, rubric)


    feedback = [
        f"Procedure coverage: {coverage_percent:.1f}%.",
        f"Total penalty applied: {total_penalty:.1f}." if APPLY_TENSE_PENALTY and total_penalty > 0 else "",
    ]

    if missing_steps:
        feedback.append(f"Unclear or missing procedural steps: {len(missing_steps)}.")

    if tense_issues:
        examples = "; ".join(tense_issues[:2])
        feedback.append(f"Sentences with incorrect tense: {len(tense_issues)} flagged. Examples: {examples}")

    if irrelevant_sentences:
        examples = "; ".join(irrelevant_sentences[:2])
        feedback.append(f"Irrelevant or off-topic sentences: {len(irrelevant_sentences)} detected. Examples: {examples}")

    keyword_summary = []
    for kf in keyword_feedback:
        if kf["missing_keywords"]:
            keyword_summary.append(
                f"Step '{kf['step'][:40]}...': Missing {', '.join(kf['missing_keywords'])}"
            )

    if keyword_summary:
        feedback.append("Keyword insight: " + " | ".join(keyword_summary))

    return {
        "rubric": rubric,
        "feedback": " ".join([f for f in feedback if f]),
        "coverage_percent": coverage_percent,
        "missing_steps": missing_steps,
        "tense_issues": tense_issues,
        "irrelevant_sentences": irrelevant_sentences,
        "keyword_feedback": keyword_feedback,
    }
import logging, re, json
from difflib import get_close_matches
# In virtuallab/constants.py
from .models import ExpectedMeasurement, VirtualExperiment, ApparatusItem
logger = logging.getLogger(__name__)
import google.generativeai as genai
import logging
import re
import json
import os
from difflib import get_close_matches
from django.conf import settings
import google.generativeai as genai
from rapidfuzz import process, fuzz
from sympy import sympify, simplify

logger = logging.getLogger(__name__)


MASTER_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "measurements": {
            "type": "object",
            "properties": {
                "evaluation_map": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "object_name": {
                                "type": "string", 
                                "description": "Must match expected_measurements exactly, lowercase"
                            },
                            "quantity": {
                                "type": "string",
                                "description": "Must match expected_measurements exactly, lowercase"
                            },
                            "instrument": {
                                "type": "string",
                                "description": "Must match expected_measurements exactly, lowercase. Use empty string '' if not specified, never null"
                            },
                            "status": {
                                "type": "string", 
                                "enum": ["match", "differ", "missing"],
                                "description": "CRITICAL: 'match' if physically reasonable (even if far from expected_value). 'differ' ONLY if physically impossible (orders of magnitude wrong, negative, calculation error). Do NOT use tolerance to decide this."
                            },
                            "student_value": {
                                "type": "string",
                                "description": "The value as extracted from student cell (e.g., '70.00')"
                            },
                            "extracted_value": {
                                "type": ["number", "null"],
                                "description": "Numeric value if parseable (e.g., 70.0), null if not a number"
                            },
                            "raw_cell_content": {
                                "type": "string",
                                "description": "Original raw cell text before any processing (e.g., 'Set 1 - 70.00 s')"
                            },
                            "critique": {
                                "type": "string",
                                "description": "Explanation ONLY for 'differ' status. Describe physical impossibility (e.g., 'Time too short for 50 oscillations', 'Period calculation error T=70 instead of 1.4'). NEVER mention tolerance or expected_value comparison here."
                            }
                        },
                        "required": ["object_name", "quantity", "instrument", "status", "raw_cell_content"]
                    }
                },
                "suspicious_values": {
                    "type": "array", 
                    "items": {"type": "string"},
                    "description": "List pattern concerns here: identical replicates, perfect linearity, exact matches to expected_value (suspicious). This is for cheating detection, not grading."
                },
                "reasoning_feedback": {
                    "type": "array", 
                    "items": {"type": "string"}
                }
            },
            "required": ["evaluation_map"]
        },
        "analysis": {
            "type": "object",
            "properties": {
                "ai_flags": {
                    "type": "array", 
                    "items": {"type": "string"}
                },
                "feedback": {
                    "type": "array", 
                    "items": {"type": "string"}
                }
            }
        },
        "discussion_conclusion": {
            "type": "object",
            "properties": {
                "discussion_indicators": {
                    "type": "object",
                    "properties": {
                        "links_results_to_theory": {"type": "boolean"},
                        "interprets_trends": {"type": "boolean"},
                        "mentions_errors": {"type": "boolean"},
                        "uses_physics_terms": {"type": "boolean"},
                        "refers_to_objective": {"type": "boolean"}
                    }
                },
                "conclusion_indicators": {
                    "type": "object",
                    "properties": {
                        "restates_objective": {"type": "boolean"},
                        "states_final_result": {"type": "boolean"},
                        "mentions_limitations": {"type": "boolean"}
                    }
                },
                "met_criteria": {
                    "type": "array", 
                    "items": {"type": "string"}
                },
                "feedback": {
                    "type": "object", 
                    "properties": {
                        "discussion": {"type": "string"},
                        "conclusion": {"type": "string"},
                        "general_notes": {
                            "type": "array", 
                            "items": {"type": "string"}
                        }
                    }
                }
            }
        },
        "references": {
            "type": "object",
            "properties": {
                "relevance_score": {"type": "number"},
                "hallucination_detected": {"type": "boolean"},
                "comment": {"type": "string"}
            }
        }
    },
    "required": ["measurements", "analysis", "discussion_conclusion", "references"]
}


def get_gemma_model():
    """Robust model initializer using the correct google-genai SDK."""
    api_key = getattr(settings, "GEMINI_API_KEY", None) or os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        logger.error("AI API Key missing.")
        return None

    try:
        return genai.Client(api_key=api_key)
    except Exception as e:
        logger.error(f"Failed to initialize GenAI Client: {e}")
        return None



OBJECT_ALIASES = {
    "copper cylinder": ["cylinder", "cylindrical rod", "rod", "cu cylinder"],
    "steel ball": ["ball bearing", "bearing", "metal ball", "stainless-steel ball"],
    "copper wire": ["wire", "cu wire", "thin wire"],
    "capillary tube": ["tube", "capillary", "glass tube", "thin tube"],
    "zero reading": ["zero reading", "zero error", "zero measurement", "reading error", "zero", "reading", "error"],
}

QUANTITY_ALIASES = {
    "mass": ["mass", "wt", "weight", "m", "mass(g)", "mass (g)", "g", "kg"],
    "length": ["length", "len", "l", "long", "distance"],
    "height": ["height", "ht", "h", "thickness", "depth"],
    "diameter": ["diameter", "dia", "ø", "d", "width", "thickness", "cross-section"],
    "zero error": ["zero error", "zero reading", "reading error", "zero", "reading", "error"],
}

INSTRUMENT_ALIASES = {
    "metre rule": [
        "metre rule", "meter rule", "metre ruler", "meter ruler",
        "metre", "meter", "rule", "ruler", "mr", "m-rule"
    ],
    "vernier calipers": [
        "vernier calipers", "vernier caliper", "vernier", "caliper", "vc", "verniers"
    ],
    "micrometer screw gauge": [
        "micrometer screw gauge", "micrometer", "screw gauge",
        "micrometer gauge", "msg", "micrometre"
    ],
    "electronic balance": [
        "electronic balance", "balance", "weighing balance",
        "weighing machine", "scale", "digital balance"
    ],
}



def canonicalize(value):
    return str(value).strip().lower() if value else ""

def reverse_alias_lookup(value, mapping, fuzzy=True):
    val = canonicalize(value)
    for canonical, aliases in mapping.items():
        if val == canonical or val in [canonicalize(a) for a in aliases]:
            return canonical
    if fuzzy:
        matches = get_close_matches(val, mapping.keys(), n=1, cutoff=0.7)
        if matches:
            return matches[0]
    return val

def detect_numeric_quantity(value):
    if isinstance(value, str):
        match = re.match(r"^\-?\d+(\.\d+)?\s*(cm3|g|kg|cm|mm)$", value.strip().lower())
        if match:
            unit = match.group(2)
            if unit in ("g", "kg"):
                return "mass"
            if unit == "cm3":
                return "volume"
            return "length/diameter/height"
    return None



LATEX_GARBAGE = re.compile(
    r"""
    \\(?:in|text|placeholder|displaylines|left|right|operatorname|mathrm)
    |\\[a-zA-Z]+(?:\{[^}]*\})?
    |[\{\}\\_]
    """,
    re.VERBOSE,
)

GREEK_ASCII = {
    "π": "pi", "ρ": "rho", "Δ": "Delta", "θ": "theta", "λ": "lambda",
    "μ": "mu", "σ": "sigma", "φ": "phi", "Ω": "Omega", "α": "alpha",
    "β": "beta", "γ": "gamma",
}

PHRASE_SPLITS = [
    (r"\bcoppercyl\b", "copper cylinder"),
    (r"\bcopperwire\b", "copper wire"),
    (r"\bsteelball\b", "steel ball"),
    (r"cap\s*pi?llary\s*tube", "capillary tube"),
    (r"copper\s*cyl\s*in\s*der", "copper cylinder"),
]

def deep_clean_student_text(raw: str) -> str:
    if not raw:
        return ""
    text = raw
    for pattern, repl in PHRASE_SPLITS:
        text = re.sub(pattern, repl, text, flags=re.I)
    text = LATEX_GARBAGE.sub(" ", text)
    for greek, ascii_ in GREEK_ASCII.items():
        text = text.replace(greek, ascii_)
    text = re.sub(r"\s+", " ", text).strip().lower()
    if not text or len(text) <= 1 or all(c in "{}\\_^~" for c in text):
        return ""
    return text

def normalize_formula(f: str) -> str:
    if not f:
        return ""
    f = f.replace("^", "**").replace("π", "pi").replace(" ", "")
    f = re.sub(r"[^a-z0-9+*\-/().]", "", f, flags=re.I)
    try:
        return str(simplify(sympify(f)))
    except Exception:
        return ""

def correct_typo(student_phrase: str, choices: list[str], threshold: int = 80) -> str | None:
    if not student_phrase or not choices:
        return None
    match, score, _ = process.extractOne(student_phrase, choices, scorer=fuzz.ratio)
    return match if score >= threshold else None

def fuzzy_set_coverage(student_items: set[str], expected_items: list[str]) -> tuple[set[str], set[str]]:
    student_items = {s for s in student_items if s.strip() and len(s.strip()) > 1}
    matched, missing = set(), set()
    expected_lower = [deep_clean_student_text(e) for e in expected_items]
    for exp in expected_lower:
        if not exp:
            continue
        if correct_typo(exp, list(student_items), threshold=80):
            matched.add(exp)
        else:
            missing.add(exp)
    return matched, missing

def formulas_equivalent(f1: str, f2: str) -> bool:
    if not (f1 and f2):
        return False
    try:
        e1, e2 = sympify(f1), sympify(f2)
        if simplify(e1 - e2) == 0:
            return True
        symbols = list(e1.free_symbols | e2.free_symbols)
        if symbols:
            subs = {s: 2 for s in symbols}
            if abs(float(e1.evalf(subs=subs)) - float(e2.evalf(subs=subs))) < 1e-3:
                return True
    except Exception:
        pass
    return fuzz.ratio(f1, f2) >= 75


GEOMETRY_PATS = [
    (re.compile(r'\\pi\s*r\^{?2}\s*h'), ['copper cylinder', 'copper wire', 'glass capillary tube']),
    (re.compile(r'\\pi\s*r\^{?2}\s*l'), ['copper wire', 'glass capillary tube']),
    (re.compile(r'\\frac\{4\}\{3\}\s*\\pi\s*r\^{?3}'), ['steel ball']),
]
DENSITY_PAT = re.compile(r'\\frac\{[^}]*m[^}]*\}\{[^}]*[vV][^}]*\}', re.I)
TYPO_FIX = {
    'coppercyl': 'copper cylinder',  'coppercylinder': 'copper cylinder',
    'steelball': 'steel ball',       'glasscapillarytube': 'glass capillary tube',
    'capillarytube': 'capillary tube', 'caplarytube': 'capillary tube',
    'copperwire': 'copper wire',     'coppercylider': 'copper cylinder',
    'zeroerrorelectronicbalance': 'zero error electronic balance',
    'zerometerrule': 'zero error meter rule',
    'zeromicrometerscrewgauge': 'zero error micrometer screw gauge',
}

def extract_from_latex(latex: str) -> tuple[set[str], set[str], set[str]]:
    if not latex:
        return set(), set(), set()
    txt = re.sub(r'\s+', ' ', latex.lower())
    objs, qtys, forms = set(), set(), set()
    for wrong, right in TYPO_FIX.items():
        txt = re.sub(rf'\b{wrong}\b', right, txt)
    for pat, cans in GEOMETRY_PATS:
        if pat.search(txt):
            objs.update(cans)
    if DENSITY_PAT.search(txt):
        qtys.add('density')
    if re.search(r'\\frac\{[^}]*m[^}]*\}', txt):
        qtys.add('mass')
    if re.search(r'\bvolume\b', txt) or re.search(r'\bV\s*=', txt):
        qtys.add('volume')
    if re.search(r'\bzero\s+error\b', txt):
        qtys.add('zero error')
    extended_aliases = {**OBJECT_ALIASES, **TYPO_FIX}
    for canon, val in extended_aliases.items():
        if isinstance(val, list):
            objs.update(val)
        else:
            objs.add(val)
    for canon in QUANTITY_ALIASES.keys():
        if re.search(rf'\b{re.escape(canon)}\b', txt):
            qtys.add(canon)
    for line in txt.splitlines():
        line_clean = re.sub(r"[^a-z0-9=+\-*/().]", "", line)
        if '=' in line_clean and any(c.isalnum() for c in line_clean):
            norm = normalize_formula(line_clean)
            if norm:
                forms.add(norm)
    objs = {o for o in objs if len(o) > 1 and not all(c in "{}\\_^~" for c in o)}
    qtys = {q for q in qtys if len(q) > 1 and not all(c in "{}\\_^~" for c in q)}
    return objs, qtys, forms

PHYSICS_UNITS = [
    "g", "kg", "mg", "m", "cm", "mm", "km", "s", "ms", "ms⁻¹", "m/s",
    "cm³", "m³", "N", "Pa", "J", "W", "C", "V", "Ω", "Hz"
]


def parse_student_rows(table, expected_objects, expected_quantities, expected_instruments):
    """Deterministic parser for table data. Returns list of row dicts."""
    rows_out = []
    data = table.get("data") or []
    headers = table.get("columns") or []
    if not data or not headers:
        return rows_out

    canon_headers = [canonicalize(h) for h in headers]
    instrument_columns = {}
    for idx, h in enumerate(canon_headers):
        inst = reverse_alias_lookup(h, expected_instruments)
        if inst in expected_instruments:
            instrument_columns[idx] = inst

    last_obj = None
    last_qty = None

    for row in data:
        if not isinstance(row, (list, tuple)):
            continue

        raw_obj = canonicalize(row[0]) if len(row) > 0 else ""
        raw_qty = canonicalize(row[1]) if len(row) > 1 else ""

        if raw_obj in ("zero error", "reading error") and not raw_qty:
            raw_qty = raw_obj
            raw_obj = "__zero__"
        if raw_obj == "" and raw_qty in ("zero error", "reading error"):
            raw_obj = "__zero__"

        if not raw_obj and last_obj:
            raw_obj = last_obj
        if not raw_qty and last_qty:
            raw_qty = last_qty

        obj = reverse_alias_lookup(raw_obj, OBJECT_ALIASES, fuzzy=True)
        qty = reverse_alias_lookup(raw_qty, QUANTITY_ALIASES, fuzzy=True)

        if raw_qty not in ("zero error", "reading error"):
            detected = detect_numeric_quantity(raw_qty)
            if detected:
                qty = detected

        if obj != "__zero__":
            last_obj = obj
        last_qty = qty

        if obj not in expected_objects and obj != "__zero__":
            continue

        if obj == "__zero__" or obj == "zero reading":
            for inst in expected_instruments:
                rows_out.append({
                    "obj": "zero reading", "qty": "zero error",
                    "inst": inst, "value": "0"
                })
        else:
            for col_idx, inst in instrument_columns.items():
                if col_idx < len(row):
                    val = str(row[col_idx]).strip()
                    if val:
                        rows_out.append({
                            "obj": obj, "qty": qty, "inst": inst, "value": val
                        })
    return rows_out

def collect_measurements_data(report, experiment):
    """
    Simplified collector that packages raw DB requirements and raw student data.
    No deterministic parsing; relies on AI mapping in the master evaluator.
    """

    expected_qs = experiment.expected_measurements.all()
    
    requirements = [
        {
            "object_name": e.object_name,
            "quantity": e.quantity,
            "instrument": e.instrument,
            "expected_value": e.expected_value,
            "expected_unit": e.expected_unit,
            "tolerance": e.tolerance,
            "marks": e.marks
        } for e in expected_qs
    ]

    student_raw_data = report.data or []

    return {
        "requirements": requirements,
        "student_raw_data": student_raw_data,
        "total_possible": sum(e.marks for e in expected_qs)
    }

import numpy as np
from difflib import SequenceMatcher

def evaluate_graph(
    submitted_points,
    expected_slope,
    expected_trend="linear",
    slope_tolerance=0.2,
    ignore_intercept=True,
    axis_labels=None,
    title=None,
):
    """
    Evaluates a student graph using best-fit regression and slope comparison.

    Parameters
    ----------
    submitted_points : list of dicts [{x, y}]
    expected_slope : float | None
    expected_trend : str
    slope_tolerance : float (fractional)
    """

    feedback = []


    points = [
        (p["x"], p["y"]) for p in submitted_points
        if isinstance(p, dict) and "x" in p and "y" in p
    ]

    if len(points) < 2:
        return {
            "slope_score": 0.0,
            "intercept_score": 0.0,
            "axis_labels_score": 0.5,
            "title_score": 0.5,
            "combined_graph_score": 1.0,
            "feedback": ["Insufficient points to determine graph trend."]
        }

    try:
        x_sub, y_sub = np.array(points).T
        sub_m, sub_c = np.polyfit(x_sub, y_sub, 1)
    except Exception as e:
        return {
            "combined_graph_score": 1.0,
            "feedback": [f"Could not compute best-fit line: {e}"]
        }

    if expected_trend == "linear":
        pass
    elif expected_trend == "constant":
        if abs(sub_m) > 1e-3:
            feedback.append("Graph should be constant, but slope is non-zero.")
    elif expected_trend == "inverse":
        feedback.append("Inverse trend detected – slope check approximated.")


    slope_score = 1.0
    if expected_slope is not None:
        if abs(expected_slope) < 1e-6:
            slope_error = abs(sub_m)
        else:
            slope_error = abs(sub_m - expected_slope) / abs(expected_slope)

        if slope_error <= slope_tolerance:
            slope_score = 1.0
        elif slope_error <= slope_tolerance * 2:
            slope_score = 0.7
        elif slope_error <= slope_tolerance * 3:
            slope_score = 0.4
        else:
            slope_score = 0.1

        if slope_score < 1.0:
            feedback.append(
                f"Expected slope ≈ {expected_slope:.3g}, obtained {sub_m:.3g}"
            )
    else:
        slope_score = 0.6
        feedback.append("Expected slope not defined; partial credit awarded.")

    intercept_score = 1.0 if ignore_intercept else max(0.0, 1.0 - abs(sub_c))


    axis_labels_score = 1.0
    if axis_labels:
        if not axis_labels.get("x") or not axis_labels.get("y"):
            axis_labels_score = 0.7

    title_score = 1.0 if title else 0.7

    physics_score = 0.85 * slope_score + 0.15 * intercept_score

    combined_graph_score = (
        physics_score +
        0.1 * axis_labels_score +
        0.05 * title_score
    ) * 10

    return {
        "slope_score": round(slope_score, 3),
        "intercept_score": round(intercept_score, 3),
        "axis_labels_score": round(axis_labels_score, 3),
        "title_score": round(title_score, 3),
        "student_slope": round(sub_m, 4),
        "combined_graph_score": round(combined_graph_score, 1),
        "feedback": feedback or ["Graph trend matches expected physics."]
    }


def collect_analysis_data(report, experiment):

    """
    Parses LaTeX and evaluates deterministic stats + graphs (if required).
    Returns a dictionary with rubric, breakdown, matched items, and feedback.
    Integrates new best-fit graph evaluation.
    """
    from QuestionBank.models import ExpectedExperimentGraph
    from difflib import SequenceMatcher

    rows = list(experiment.expected_data_analysis.all())


    if not rows:
        data_analysis_result = {
            "deterministic_score": {
                "rubric": 0,
                "breakdown": {},
                "matched": {},
                "feedback": "No data analysis expected."
            },
            "raw_data": {}
        }
    else:
        expected_objs  = {reverse_alias_lookup(r.object_name, OBJECT_ALIASES) for r in rows}
        expected_qtys  = {reverse_alias_lookup(r.quantity, QUANTITY_ALIASES) for r in rows}
        expected_forms = {normalize_formula(r.formula_latex) for r in rows if r.formula_latex}

        raw_latex = report.data_analysis or ""
        student_objs, student_qtys, student_forms = extract_from_latex(raw_latex)

        # Cleanup
        student_objs = {o for o in student_objs if o.strip() and len(o.strip()) > 1}
        student_qtys = {q for q in student_qtys if q.strip() and len(q.strip()) > 1}
        student_forms = {f for f in student_forms if f.strip()}

        matched_objs, missing_objs = fuzzy_set_coverage(student_objs, list(expected_objs))
        matched_qtys, missing_qtys = set(), set()
        for exp_qty in expected_qtys:
            match = correct_typo(exp_qty, list(student_qtys), threshold=70)
            if match:
                matched_qtys.add(exp_qty)
            else:
                for s_qty in student_qtys:
                    if exp_qty in s_qty or any(u in s_qty for u in PHYSICS_UNITS):
                        matched_qtys.add(exp_qty)
                        break
                else:
                    missing_qtys.add(exp_qty)

        formula_scores = {}
        for exp_f in expected_forms:
            best_score = 0
            for stu_f in student_forms:
                if not stu_f or (len(stu_f) == 1 and stu_f.isalpha()) or stu_f.replace('.', '', 1).isdigit():
                    continue
                if formulas_equivalent(exp_f, stu_f):
                    best_score = 1.0
                    break
                else:
                    sim = fuzz.ratio(exp_f, stu_f) / 100
                    best_score = max(best_score, sim * 0.5)
            formula_scores[exp_f] = best_score

        form_cov = sum(formula_scores.values()) / max(1, len(expected_forms))
        obj_cov  = len(matched_objs) / max(1, len(expected_objs))
        qty_cov  = len(matched_qtys) / max(1, len(expected_qtys))
        data_analysis_rubric = 0.2 * obj_cov + 0.6 * qty_cov + 0.2 * form_cov

        feedback_parts = []
        if missing_objs:  feedback_parts.append("Missing objects: " + ", ".join(sorted(missing_objs)))
        if missing_qtys:  feedback_parts.append("Missing quantities: " + ", ".join(sorted(missing_qtys)))
        missing_formulas = [f for f, score in formula_scores.items() if score < 1.0]
        if missing_formulas:
            feedback_parts.append("Missing/partially correct formulas: " + ", ".join(sorted(missing_formulas)))

        data_analysis_result = {
            "deterministic_score": {
                "rubric": round(data_analysis_rubric * 10, 1),
                "breakdown": {
                    "object_coverage": round(obj_cov, 3),
                    "quantity_coverage": round(qty_cov, 3),
                    "formula_coverage": round(form_cov, 3),
                },
                "matched": {
                    "objects": list(matched_objs),
                    "quantities": list(matched_qtys),
                    "formulas": [f for f, score in formula_scores.items() if score > 0],
                },
                "feedback": "; ".join(feedback_parts) if feedback_parts else "All items covered.",
            },
            "raw_data": {
                "student_objects": list(student_objs),
                "student_quantities": list(student_qtys),
                "student_formulas": list(student_forms),
                "expected_formulas": list(expected_forms)
            }
        }


    if getattr(experiment, "needs_graph", False):
        expected_graphs = experiment.expected_graphs.all()
        graph_feedback = []
        graph_rubrics = []
        graphs_data = {}

        def similar(a, b, threshold=0.3):
            return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= threshold

        for g in expected_graphs:
            student_graphs = report.graphs.all()
            matched_graph = next(
                (sg for sg in student_graphs if sg.title and g.title and similar(sg.title, g.title)),
                None
            )

            submitted_points = matched_graph.points_json if matched_graph else []
            expected_points = g.points_json if hasattr(g, "points_json") and g.points_json else []

            res = evaluate_graph(
                submitted_points=submitted_points,
                expected_slope=g.expected_slope,
                expected_trend=g.expected_trend,
                axis_labels={"x": g.x_quantity, "y": g.y_quantity},
                title=g.title
            )


            graph_rubrics.append(res["combined_graph_score"])
            graph_feedback.extend([f"{g.title}: {fb}" for fb in res["feedback"]])


            graphs_data[g.title] = {
                "slope_score": res.get("slope_score", 0),
                "intercept_score": res.get("intercept_score", 0),
                "axis_labels_score": res.get("axis_labels_score", 0),
                "title_score": res.get("title_score", 0),
                "student_slope": res.get("student_slope", None),   
                "combined_graph_score": res.get("combined_graph_score", 0),
                "feedback": res.get("feedback", [])
            }


        avg_graph_rubric = sum(graph_rubrics) / max(1, len(graph_rubrics))
        combined_rubric = round(
            0.7 * data_analysis_result["deterministic_score"]["rubric"]
            + 0.3 * avg_graph_rubric,
            1
        )
        combined_feedback = "; ".join([data_analysis_result["deterministic_score"]["feedback"]] + graph_feedback)

        return {
            "deterministic_score": {
                "rubric": combined_rubric,
                "breakdown": {
                    "data_analysis_rubric": data_analysis_result["deterministic_score"]["rubric"],
                    "graph_rubric": avg_graph_rubric
                },
                "feedback": combined_feedback,
                "matched": {
                    "data_analysis": data_analysis_result["deterministic_score"]["matched"],
                    "graphs": {} 
                }
            },
            "raw_data": {
                "data_analysis": data_analysis_result["raw_data"],
                "graphs": graphs_data
            }
        }

    return data_analysis_result


def collect_reference_data(report):
    """Regex based reference checking. NO API CALLS."""
    refs = (report.references or "").strip()
    breakdown = {}
    rubric = 0
    fb = []

    if not refs or len(refs.split()) < 3:
        return {
            "rubric": 0, 
            "breakdown": {"presence": False}, 
            "feedback_list": ["No usable references provided."], 
            "refs_text": refs
        }

    breakdown["presence"] = True
    ref_candidates = re.split(r"\n|;|\d\.\s", refs)
    ref_candidates = [r.strip() for r in ref_candidates if len(r.strip()) > 8]
    count = len(ref_candidates)
    breakdown["reference_count"] = count

    if count >= 4: rubric += 2; fb.append("References list contains multiple entries.")
    elif count >= 2: rubric += 1; fb.append("References list is small but present.")
    else: fb.append("Only one reference detected.")

    apa_pattern = r"[A-Z][a-z]+\,\s[A-Z]\.\s\(\d{4}\)"
    mla_pattern = r"[A-Z][a-z]+\,\s[A-Z][a-z]+\."
    ieee_pattern = r"\[\d+\]\s"
    url_pattern = r"https?://[^\s]+"
    doi_pattern = r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+"

    score_fmt = 0
    found_patterns = []
    if re.search(apa_pattern, refs): score_fmt += 2; found_patterns.append("APA")
    if re.search(mla_pattern, refs): score_fmt += 1; found_patterns.append("MLA")
    if re.search(ieee_pattern, refs): score_fmt += 2; found_patterns.append("IEEE")
    if re.search(url_pattern, refs): score_fmt += 1; found_patterns.append("URL")
    if re.search(doi_pattern, refs): score_fmt += 2; found_patterns.append("DOI")

    breakdown["formatting"] = found_patterns or ["none"]
    rubric += min(score_fmt, 3)

    if score_fmt > 0: fb.append(f"Recognized formatting: {', '.join(found_patterns)}.")
    else: fb.append("No recognizable academic formatting.")

    return {
        "rubric": rubric,
        "breakdown": breakdown,
        "feedback_list": fb,
        "refs_text": refs
    }
# ──────────────────────────────
# 6. UNIFIED MASTER EVALUATOR
# ──────────────────────────────
def evaluate_lab_report_unified(report, experiment):
    """
    The Single-Shot Evaluator.
    Runs all collectors, builds one prompt, calls Gemini ONCE, and merges results.
    Adaptive Mapping: Uses AI to map raw JSON tables to ExpectedMeasurement DB fields.
    """

    meas_data = collect_measurements_data(report, experiment)
    anal_data = collect_analysis_data(report, experiment)
    ref_data  = collect_reference_data(report)

    context_payload = {
        "experiment": {
            "title": experiment.title,
            "objective": experiment.objective,
            "theory": experiment.theory,
            "method": experiment.method_summary,
            "expected_measurements": meas_data.get("requirements", []),  
            "expected_formulas": anal_data.get("raw_data", {}).get("expected_formulas", [])
        },
        "submission": {
            "student_tables": meas_data.get("student_raw_data", []), # Messy JSON tables
            "data_analysis_latex": getattr(report, "data_analysis", ""), # MathQuill LaTeX
            "discussion": report.discussion,
            "conclusion": report.conclusion,
            "references": ref_data.get("refs_text", "")
        }
    }

    prompt = f"""
    You are a Physics Lab Examiner. Perform a comprehensive evaluation of this student report.

    INPUT DATA:
    {json.dumps(context_payload, default=str)}

    TASKS:

    1. MEASUREMENTS MAPPING (Pattern-Based Physics Validation):
    Cross-check 'student_tables' against 'expected_measurements'.
    
    MAPPING RULES:
    - Use EXACT strings from 'expected_measurements' for object_name, quantity, and instrument fields
    - Normalize student abbreviations using this logic:
        * "0.5 M" or "0.5m" → object_name="Pendulum (0.5m)", quantity="Length"
        * "10.0 degrees" or "10°" → object_name="Pendulum (10° amplitude)", quantity="Amplitude"
        * "Set 1 - 70.00 s" → extract value=70.00, quantity="Time for 50 oscillations (Set 1)"
        * "Set 2 - 84.00 s" → extract value=84.00, quantity="Time for 50 oscillations (Set 2)"
    - For compound cells with "Set X - [value]", split on "-" and extract the numeric value
    - If instrument is unclear from student data → use empty string "" (never null)
    - All returned strings must be lowercase to match database keys
    
    PHYSICAL PLAUSIBILITY CHECKS (Adaptive - Works for Any Experiment):
    Analyze the EXPECTED MEASUREMENTS REFERENCE below to detect unreasonable values dynamically:
    
    A. RANGE DETECTION (Auto-calculated):
       - Calculate min_expected and max_expected for each quantity type from the reference data
       - Reasonable student range: [min_expected × 0.5, max_expected × 2.0]
       - IMPOSSIBLE: < min_expected × 0.1 or > max_expected × 5.0 (orders of magnitude wrong)
       - Example: If expected times are 70-100s, student value of 5s or 500s is physically impossible
    
    B. PATTERN CONSISTENCY:
       - If object_name varies by parameter (e.g., "Pendulum (0.5m)" → "Pendulum (1.0m)"), check if student values follow the same trend as expected_values
       - FLAG "differ" if: Expected increases but student decreases (inverse trend)
       - FLAG suspicious_values if: All student values are identical across different objects (copy-paste error)
       - FLAG suspicious_values if: Variance is suspiciously perfect (likely calculated, not measured)
    
    C. SET/REPLICATE CONSISTENCY:
       - If quantities contain "(Set 1)" and "(Set 2)", compare student values
       - Reasonable: Within 10-20% of each other (experimental variance)
       - Suspicious: Identical to 2+ decimal places (fabrication)
       - Differing: >30% variance suggests procedural error
    
    D. UNIT CONTEXT RULES:
       - If quantity contains "period", "time", "oscillation": Check values are reasonable for lab duration (< 1 hour typically)
       - If quantity contains "length", "diameter", "height": Check values fit lab equipment (0.001m to 5m typically)
       - If quantity contains "error", "zero": Should be small relative to measurement (< 5% of typical value)
    
    STATUS DECISION TREE:
    1. Empty/null raw_cell_content → "missing"
    2. Outside [min×0.1, max×5.0] range → "differ" + critique "Physically impossible [reason]"
    3. Violates scaling pattern (wrong trend) → "differ" + critique "Inconsistent with physical relationship"
    4. Edge case but plausible → "match" + add to suspicious_values list
    5. Normal → "match"
    
    IMPORTANT: Do not compare exact decimals. Compare orders of magnitude and trends only.
    
    EXPECTED MEASUREMENTS REFERENCE (for pattern analysis):
    {json.dumps([{
        "object_name": e.object_name, 
        "quantity": e.quantity, 
        "instrument": e.instrument or "",
    } for e in experiment.expected_measurements.all()], indent=2)}
    
    INSTRUCTION: Infer physics relationships from expected_value patterns above. Use these only to establish reasonable ranges, not for exact matching.

    2. ANALYSIS: 
    Check 'data_analysis_latex' to ensure formulas match 'expected_formulas'.
    Verify that calculations reference the correct variables (T for period, l for length).

    3. DISCUSSION & CONCLUSION:
    - Identify if key reasoning elements are PRESENT. Implicit understanding counts.
    - Look for: links between results and theory, error mentions, physics terminology
    - Undergraduate level; ignore grammar/fluency issues.

    4. REFERENCES: 
    Check for relevance and potential hallucinations.
    Verify URLs/authors exist in the submitted text.

    OUTPUT:
    Return strictly VALID JSON matching this schema:
    {json.dumps(MASTER_REPORT_SCHEMA, indent=2)}

    IMPORTANT: All string values in the evaluation_map must be lowercase and match the expected_measurements reference exactly. Use empty strings for missing instruments, never null.
    """


    ai_result = {
        "measurements": {"evaluation_map": [], "suspicious_values": [], "reasoning_feedback": []},
        "analysis": {"ai_flags": [], "feedback": []},
        "discussion_conclusion": {
            "discussion_indicators": {},
            "conclusion_indicators": {},
            "met_criteria": [],
            "feedback": {"discussion": "", "conclusion": "", "general_notes": []}
        },
        "references": {"relevance_score": 0, "hallucination_detected": False, "comment": ""}
    }

    client = get_gemma_model()
    

    system_instr = (
        "You are a Physics Lab Examiner. Analyze student data for physical plausibility. "
        "Strictly follow mapping rules and return data in the requested JSON format."
    )

    if client:
        try:
         
            resp = client.models.generate_content(
                model="gemma-4-31b-it",
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    system_instruction=system_instr,
                    temperature=0,  
                    response_mime_type="application/json",
             
                    thinking_config=genai.types.ThinkingConfig(thinking_level="medium"),
                    max_output_tokens=1500,
                )
            )
            ai_result = json.loads(resp.text)
        except Exception as e:
            logger.error(f"Gemma 4 Evaluation Failed: {e}")

    # 4. MERGE & RETURN
    
    DISCUSSION_WEIGHTS = {
        "links_results_to_theory": 3, "interprets_trends": 2, "mentions_errors": 2,
        "uses_physics_terms": 1, "refers_to_objective": 2,
    }

    CONCLUSION_WEIGHTS = {
        "restates_objective": 3, "states_final_result": 4, "mentions_limitations": 3,
    }

    def score_from_indicators(indicators, weights):
        return sum(w for k, w in weights.items() if indicators.get(k))


    m_ai = ai_result.get("measurements", {})
    eval_map = m_ai.get("evaluation_map", [])
    
 

    # Safety check
    if not eval_map:
        logger.error("AI returned empty evaluation_map - using empty evaluation")
    
   
    db_expected = list(experiment.expected_measurements.all())
    marks_lookup = {}
    
    for e in db_expected:
        obj = (e.object_name or "").strip().lower()
        qty = (e.quantity or "").strip().lower()
        inst = (e.instrument or "").strip().lower()
        
   
        marks_lookup[f"{obj}|{qty}|{inst}"] = e.marks
       
        marks_lookup[f"{obj}|{qty}|"] = e.marks
    
    total_possible = sum(e.marks for e in db_expected)  # Keep this
    total_awarded = 0
    m_feedback = []
    processed_keys = set()
    
    for item in eval_map:
        obj = str(item.get("object_name") or "").strip().lower()
        qty = str(item.get("quantity") or "").strip().lower()
        inst = str(item.get("instrument") or "").strip().lower()
        
        obj = re.sub(r'(\d+)\.0+°', r'\1°', obj)
        qty = re.sub(r'(\d+)\.0+°', r'\1°', qty)
        
    
        lookup_key = f"{obj}|{qty}|{inst}"
        marks = marks_lookup.get(lookup_key)
        

        if marks is None:
            lookup_key = f"{obj}|{qty}|"
            marks = marks_lookup.get(lookup_key)
        

        if marks is None and "(" in qty:
            base_qty = qty.split("(")[0].strip()
            lookup_key = f"{obj}|{base_qty}|"
            marks = marks_lookup.get(lookup_key)
        
      
        if lookup_key in processed_keys:
            continue
        processed_keys.add(lookup_key)
        
        status = item.get("status")
        
        if status == "match" and marks is not None:
            total_awarded += marks
        elif status == "differ":
            m_feedback.append(f"{obj} ({qty}): {item.get('critique', 'Improbable value')}")
        elif status == "missing":
            m_feedback.append(f"{obj} ({qty}): Missing")

    
    m_det = {
        "total_awarded": total_awarded,
        "total_possible": total_possible,
        "rubric": round((total_awarded / max(1, total_possible)) * 10, 1),
        "feedback": "; ".join(m_feedback),
        "ai_flags": m_ai.get("suspicious_values", [])
    }

    
    a_det = anal_data.get("deterministic_score", {"score": 0, "feedback": "No analysis data"})
    a_ai = ai_result.get("analysis", {})
    a_det["ai_flags"] = a_ai.get("ai_flags", [])

    feedback_parts = ["Data analysis feedback: All items covered."]
    if getattr(experiment, "needs_graph", False):

        pass
    if a_ai.get("feedback"):
        feedback_parts.append("; ".join(a_ai.get("feedback", [])))
    
    analysis_feedback_set = {p.strip().strip(";") for p in feedback_parts if p.strip()}
    a_det["feedback"] = "; ".join(sorted(analysis_feedback_set))

 
    d_ai = ai_result.get("discussion_conclusion", {})
    disc_indicators = d_ai.setdefault("discussion_indicators", {})
    conc_indicators = d_ai.setdefault("conclusion_indicators", {})

    for k in DISCUSSION_WEIGHTS: disc_indicators.setdefault(k, False)
    for k in CONCLUSION_WEIGHTS: conc_indicators.setdefault(k, False)

    d_final = {
        "rubric": {
            "discussion": min(score_from_indicators(disc_indicators, DISCUSSION_WEIGHTS), 10),
            "conclusion": min(score_from_indicators(conc_indicators, CONCLUSION_WEIGHTS), 10)
        },
        "feedback": d_ai.get("feedback", {}),
        "checklist": d_ai.get("met_criteria", [])
    }

 
    r_det = ref_data
    r_ai = ai_result.get("references", {})
    final_ref_score = r_det["rubric"] + min(r_ai.get("relevance_score", 0), 3)

    r_final = {
        "rubric": min(final_ref_score, 10),
        "breakdown": r_det["breakdown"],
        "feedback": f"{' '.join(r_det.get('feedback_list', []))} {r_ai.get('comment', '')}".strip(),
        "hallucination": r_ai.get("hallucination_detected", False)
    }

    return {
        "measurements": m_det,
        "analysis": a_det,
        "discussion": d_final,
        "references": r_final
    }