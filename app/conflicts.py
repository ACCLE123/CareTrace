"""Small, deterministic clinical-content conflict detector for the demo.

This deliberately does not infer diagnoses or resolve disagreements. It only
flags a few transparent, high-value contradiction classes for clinician review.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ConflictCandidate:
    category: str
    reason: str


ALLERGENS = ("penicillin", "amoxicillin", "aspirin", "ibuprofen", "latex")
PLAN_TESTS = ("ecg", "troponin", "x-ray", "ct scan")
DOSE_RE = re.compile(r"\b([a-z][a-z-]{2,})\s+(\d+(?:\.\d+)?)\s*(mg|mcg|g)\b", re.IGNORECASE)


def _allergy_state(text: str, allergen: str) -> bool | None:
    value = text.lower()
    escaped = re.escape(allergen)
    if re.search(rf"\b(?:no|denies|without)\s+(?:known\s+)?{escaped}\s+allerg(?:y|ies)\b", value) or re.search(rf"\bnot\s+allergic\s+to\s+{escaped}\b", value):
        return False
    if re.search(rf"\b{escaped}\s+allerg(?:y|ic)\b", value) or re.search(rf"\ballerg(?:y|ic)\s+to\s+{escaped}\b", value):
        return True
    return None


def _doses(text: str) -> dict[str, int]:
    doses: dict[str, int] = {}
    for medicine, raw_amount, unit in DOSE_RE.findall(text):
        amount = float(raw_amount)
        normalized_mcg = int(amount * {"mcg": 1, "mg": 1000, "g": 1_000_000}[unit.lower()])
        doses[medicine.lower()] = normalized_mcg
    return doses


def _plan_state(text: str, test: str) -> bool | None:
    value = text.lower()
    escaped = re.escape(test)
    negative = rf"(?:cancel(?:led)?|not\s+(?:order(?:ed)?|request(?:ed)?|planned?)|no\s+(?:order|request|plan)).{{0,30}}\b{escaped}\b|\b{escaped}\b.{{0,30}}(?:cancel(?:led)?|not\s+(?:ordered|requested|planned?))"
    positive = rf"(?:order(?:ed)?|request(?:ed)?|plan(?:ned)?).{{0,30}}\b{escaped}\b|\b{escaped}\b.{{0,30}}(?:order(?:ed)?|request(?:ed)?|plan(?:ned)?)"
    if re.search(negative, value):
        return False
    if re.search(positive, value):
        return True
    return None


def detect_conflicts(new_text: str, prior_text: str) -> list[ConflictCandidate]:
    """Return only directly contradictory, explainable matches between two notes."""
    matches: list[ConflictCandidate] = []
    for allergen in ALLERGENS:
        new_state, prior_state = _allergy_state(new_text, allergen), _allergy_state(prior_text, allergen)
        if new_state is not None and prior_state is not None and new_state != prior_state:
            matches.append(ConflictCandidate("allergy", f"Conflicting {allergen} allergy statements."))

    new_doses, prior_doses = _doses(new_text), _doses(prior_text)
    for medicine in sorted(new_doses.keys() & prior_doses.keys()):
        if new_doses[medicine] != prior_doses[medicine]:
            matches.append(ConflictCandidate("medication_dose", f"Conflicting documented dose for {medicine}."))

    for test in PLAN_TESTS:
        new_state, prior_state = _plan_state(new_text, test), _plan_state(prior_text, test)
        if new_state is not None and prior_state is not None and new_state != prior_state:
            matches.append(ConflictCandidate("care_plan", f"Conflicting documented plan for {test.upper()}."))
    return matches
