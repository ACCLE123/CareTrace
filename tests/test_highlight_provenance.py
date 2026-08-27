from app.policy import Actor, CareStore, Role


def test_highlight_from_ai_scribed_note_resolves_to_exact_timeline_entry():
    store = CareStore()
    system = Actor("scribe", "clinic-a", Role.SYSTEM)
    entry = store.add_entry(system, entry_type="ai_doctor_consult_summary", content="Chest pain requires clinician review.", provenance_pointer="consult:42")
    highlight = store.create_highlight(entry.id, "Chest pain requires clinician review.", "Safety floor: escalation language.")

    assert highlight.provenance_pointer == f"timeline:{entry.id}#source"
    assert store.resolve_provenance(highlight.provenance_pointer) is entry
    assert highlight.importance >= 80

