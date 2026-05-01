"""
ICD Code Evaluator

Rule-based evaluation of ICD-10 code predictions — no LLM call.
Scores on accuracy, completeness, and specificity identical to the
former icd_code_judge hybrid evaluator, but instant and deterministic.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseEvaluator, EvaluationResult


def _extract_codes(raw) -> List[Dict]:
    """
    Extract a list of {code, type} dicts from the LLM response or expected value.
    Handles:
      - dict with 'codes' key ({"codes": [{"code": ..., "type": ...}, ...]})
      - list of code dicts directly
      - JSON embedded in a markdown code fence in a string
    """
    if isinstance(raw, dict) and 'codes' in raw:
        return raw['codes']
    if isinstance(raw, list):
        return raw

    if isinstance(raw, str):
        # Strip markdown fences
        text = raw.strip()
        fence_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
        if fence_match:
            text = fence_match.group(1)
        else:
            # Find the first {...} block
            brace_match = re.search(r'\{[\s\S]*\}', text)
            if brace_match:
                text = brace_match.group(0)
        # Try 1: clean JSON parse
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and 'codes' in parsed:
                return parsed['codes']
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

        # Try 2: repair common LLM hallucination artifacts (stray words inside JSON)
        # e.g. {"code":al "E78.1" → {"code": "E78.1"
        cleaned = re.sub(r'(?<=:)\s*[a-zA-Z_]+\s+(?=")', ' ', text)
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and 'codes' in parsed:
                return parsed['codes']
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

        # Try 3: regex fallback — extract all "code": "XXXXX" pairs from malformed JSON
        code_matches = re.findall(r'"code"\s*:\s*"([A-Z][0-9A-Z.]+)"', text)
        type_matches = re.findall(r'"type"\s*:\s*"([^"]+)"', text)
        if code_matches:
            return [
                {'code': c, 'type': type_matches[i] if i < len(type_matches) else 'SECONDARY'}
                for i, c in enumerate(code_matches)
            ]

    return []


def _normalize_code(code: str) -> str:
    """Uppercase and strip whitespace."""
    return code.strip().upper()


def _code_prefix(code: str, chars: int = 3) -> str:
    """Return the first N characters of the code (category level)."""
    return _normalize_code(code)[:chars]


def evaluate_icd_codes(
    predicted: List[Dict],
    expected: List[Dict],
) -> Tuple[float, Dict]:
    """
    Score predicted codes against expected codes.

    Returns (score 0.0-1.0, details dict).

    Scoring weights:
      - Accuracy     40%  — correct codes (full match)
      - Completeness 25%  — all expected codes present
      - Specificity  10%  — codes at correct specificity level
      - Precision    25%  — penalises over-coding (extra irrelevant codes)
    """
    if not expected:
        return 1.0, {"note": "No expected codes defined"}

    exp_codes = [_normalize_code(c.get('code', '')) for c in expected]
    pred_codes = [_normalize_code(c.get('code', '')) for c in predicted]
    exp_set = set(exp_codes)
    pred_set = set(pred_codes)

    # --- Prefix match: K29.8 ↔ K29.80 (one is a direct prefix of the other) ---
    # Treated as equivalent to exact match for all scoring purposes.
    prefix_matched_exp = set()
    for exp_c in exp_codes:
        if exp_c in pred_set:
            prefix_matched_exp.add(exp_c)  # exact hit already
            continue
        for pred_c in pred_codes:
            if exp_c.startswith(pred_c) or pred_c.startswith(exp_c):
                prefix_matched_exp.add(exp_c)
                break

    # --- Accuracy (45%): how many predicted codes exactly/prefix match expected ---
    exact_hits = exp_set & pred_set
    accuracy_ratio = len(prefix_matched_exp) / len(exp_set) if exp_set else 1.0

    # Partial credit: 3-char category level match (for non-prefix misses)
    exp_cats = {_code_prefix(c) for c in exp_codes}
    pred_cats = {_code_prefix(c) for c in pred_codes}
    cat_hits = exp_cats & pred_cats
    cat_ratio = len(cat_hits) / len(exp_cats) if exp_cats else 1.0

    # Accuracy score: prefix/exact match full credit, category-only match worth half
    accuracy_score = accuracy_ratio  # prefix matches already at full credit

    # --- Completeness (30%): are all expected codes present in prediction? ---
    # Use category-level match: M45 for M45.9 = complete (specificity handles the rest)
    completeness_score = cat_ratio

    # --- Specificity (15%): predicted codes at correct specificity level ---
    # Expected code length = specificity target; penalty for shorter predictions.
    # No penalty if predicted is a direct prefix of expected (e.g. K29.8 for K29.80).
    specificity_penalties = 0
    for exp_c in exp_codes:
        # Find best matching predicted code (same category)
        candidates = [p for p in pred_codes if _code_prefix(p) == _code_prefix(exp_c)]
        if not candidates:
            specificity_penalties += 1
            continue
        best = max(candidates, key=lambda p: len(p))
        if len(best) < len(exp_c):
            # Tolerate if predicted is a direct prefix of expected (K29.8 → K29.80)
            if not exp_c.startswith(best):
                specificity_penalties += 0.5  # genuinely under-specified
        # Over-specification is fine (more specific than expected is OK)

    specificity_score = max(0.0, 1.0 - specificity_penalties / len(exp_codes))

    # --- Precision (10%): penalise severe over-coding ---
    # What fraction of predicted codes actually match an expected code?
    matched_pred = set()
    for pred_c in pred_codes:
        for exp_c in exp_codes:
            if pred_c == exp_c or pred_c.startswith(exp_c) or exp_c.startswith(pred_c):
                matched_pred.add(pred_c)
                break
    precision_raw = len(matched_pred) / len(pred_codes) if pred_codes else 1.0
    # Stricter curve: precision_raw >= 0.8 → full score; below 0.8 → linear penalty
    precision_score = min(1.0, precision_raw / 0.8)

    # --- Weighted total (must sum to 1.0) ---
    weighted = (accuracy_score * 0.40 + completeness_score * 0.25
                + specificity_score * 0.10 + precision_score * 0.25)
    weighted = round(min(1.0, max(0.0, weighted)), 4)

    # --- Status ---
    if weighted >= 0.85:
        status = 'passed'
    elif weighted >= 0.50:
        status = 'partial'
    else:
        status = 'failed'

    # --- Diff details for debugging ---
    # Build prefix-match pairs (pred→exp) so missing/extra exclude them
    prefix_pairs = {}  # pred_code → exp_code
    for exp_c in exp_codes:
        if exp_c in pred_set:
            continue  # exact match, not prefix
        for pred_c in pred_codes:
            if pred_c in exp_set:
                continue  # exact match on pred side
            if exp_c.startswith(pred_c) or pred_c.startswith(exp_c):
                prefix_pairs[pred_c] = exp_c
                break

    missing = sorted((exp_set - pred_set) - set(prefix_pairs.values()))
    extra = sorted((pred_set - exp_set) - set(prefix_pairs.keys()))

    details = {
        'accuracy_score': round(accuracy_score, 3),
        'completeness_score': round(completeness_score, 3),
        'specificity_score': round(specificity_score, 3),
        'precision_score': round(precision_score, 3),
        'weighted_score': weighted,
        'expected_codes': exp_codes,
        'predicted_codes': pred_codes,
        'exact_matches': sorted(exact_hits),
        'prefix_matches': {k: v for k, v in sorted(prefix_pairs.items())},
        'prefix_matched_pred': sorted(matched_pred),
        'missing_codes': missing,
        'extra_codes': extra,
        'method': 'rule_based',
    }

    return weighted, details


class IcdCodeEvaluator(BaseEvaluator):
    """
    Evaluates ICD-10 coding responses without any LLM call.
    Instant, deterministic, never times out.
    """

    def __init__(self, domain: str = 'icd_coding'):
        self._domain = domain

    @property
    def name(self) -> str:
        return 'ICD Code Evaluator'

    @property
    def uses_pass2(self) -> bool:
        return False

    def evaluate(self, response: str, expected: Any, level: int = 1, prompt: str = '') -> EvaluationResult:
        predicted = _extract_codes(response)
        expected_list = _extract_codes(expected)

        if not expected_list:
            return EvaluationResult(
                score=0.0,
                status='failed',
                details={'error': 'Could not parse expected codes', 'raw_expected': str(expected)[:200]},
            )

        if not predicted:
            return EvaluationResult(
                score=0.0,
                status='failed',
                details={
                    'error': 'Could not extract codes from response',
                    'raw_response': response[:300],
                    'expected_codes': [c.get('code') for c in expected_list],
                    'method': 'rule_based',
                },
            )

        score, details = evaluate_icd_codes(predicted, expected_list)

        return EvaluationResult(
            score=score,
            status='passed' if score >= 0.85 else ('partial' if score >= 0.50 else 'failed'),
            details=details,
            extracted_answer=json.dumps([c.get('code') for c in predicted]),
            pass2_used=False,
        )
