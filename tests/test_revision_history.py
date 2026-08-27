import pytest

from app.policy import Actor, CareStore, Role


def test_edit_increments_version_revert_restores_prior_content_and_audits_metadata_only():
    store = CareStore()
    clinician = Actor("doctor-1", "clinic-a", Role.CLINICIAN)
    entry = store.add_entry(clinician, entry_type="clinician_note", content="Initial assessment.")
    updated = store.edit(clinician, entry.id, "Updated assessment and plan.", expected_version=1)

    assert updated.version == 2
    reverted = store.revert(clinician, entry.id, target_version=1, expected_version=2)
    assert reverted.content == "Initial assessment."
    assert reverted.version == 3
    assert [event["action"] for event in store.audit][-2:] == ["entry_updated", "entry_reverted"]
    assert all(event["metadata_only"] for event in store.audit)
    assert all("content" not in event for event in store.audit)

