from app.conflicts import detect_conflicts


def test_deterministic_conflict_detector_flags_only_opposed_supported_claims():
    earlier = "Patient-reported penicillin allergy. Metformin 500 mg documented. ECG order requested."
    newer = "No known penicillin allergy. Metformin 1000 mg documented. ECG order cancelled."

    conflicts = detect_conflicts(newer, earlier)

    assert {(item.category, item.reason) for item in conflicts} == {
        ("allergy", "Conflicting penicillin allergy statements."),
        ("medication_dose", "Conflicting documented dose for metformin."),
        ("care_plan", "Conflicting documented plan for ECG."),
    }


def test_matching_or_unrelated_notes_are_not_presented_as_conflicts():
    assert detect_conflicts("Penicillin allergy: hives.", "Penicillin allergy: hives.") == []
    assert detect_conflicts("Follow-up call scheduled.", "ECG order requested.") == []
