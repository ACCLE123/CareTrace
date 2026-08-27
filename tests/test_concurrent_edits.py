import pytest

from app.policy import Actor, CareStore, ConflictError, Role


def test_different_role_owned_sections_do_not_overwrite_each_other_and_same_section_is_optimistic():
    store = CareStore()
    staff = Actor("staff-1", "clinic-a", Role.STAFF)
    clinician = Actor("doctor-1", "clinic-a", Role.CLINICIAN)
    staff_entry = store.add_entry(staff, entry_type="staff_note", content="Follow-up call due.", section="coordination")
    clinician_entry = store.add_entry(clinician, entry_type="clinician_note", content="Plan: order ECG.", section="assessment")

    store.edit(staff, staff_entry.id, "Follow-up call booked.", expected_version=1)
    store.edit(clinician, clinician_entry.id, "Plan: order ECG and troponin.", expected_version=1)
    assert store.entries[staff_entry.id].content == "Follow-up call booked."
    assert store.entries[clinician_entry.id].content == "Plan: order ECG and troponin."

    store.edit(clinician, clinician_entry.id, "Plan: ECG completed.", expected_version=2)
    with pytest.raises(ConflictError):
        store.edit(clinician, clinician_entry.id, "Stale browser write.", expected_version=2)

