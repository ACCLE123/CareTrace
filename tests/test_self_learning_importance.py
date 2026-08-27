from app.policy import Actor, CareStore, Role


def test_accepted_suggestions_increase_future_same_type_priority_but_not_above_safety_bounds():
    store = CareStore()
    system = Actor("scribe", "clinic-a", Role.SYSTEM)
    first = store.add_entry(system, entry_type="ai_nurse_consult_summary", content="Medication question noted.")
    accepted = store.create_highlight(first.id, "Medication question", "Suggested for review")
    store.record_feedback(accepted.id, accepted=True)
    future = store.add_entry(system, entry_type="ai_nurse_consult_summary", content="A second medication question noted.")
    improved = store.create_highlight(future.id, "Second medication question", "Suggested for review")

    assert improved.importance == accepted.importance + 5
    assert improved.importance <= 100

