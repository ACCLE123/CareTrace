import pytest

from app.policy import Actor, AuthorizationError, CareStore, Role, can_read_entry, require_same_clinic


def test_staff_and_clinician_cannot_write_as_each_other():
    store = CareStore()
    staff = Actor("staff-1", "clinic-a", Role.STAFF)
    clinician = Actor("doctor-1", "clinic-a", Role.CLINICIAN)
    staff_note = store.add_entry(staff, entry_type="staff_note", content="Medication reconciliation requested.")
    clinician_note = store.add_entry(clinician, entry_type="clinician_note", content="Assessment and plan reviewed.")

    with pytest.raises(AuthorizationError):
        store.edit(clinician, staff_note.id, "Clinician cannot overwrite staff note.", 1)
    with pytest.raises(AuthorizationError):
        store.edit(staff, clinician_note.id, "Staff cannot overwrite clinical assessment.", 1)


def test_patient_cannot_view_raw_ai_or_internal_collaboration_and_cross_clinic_is_denied():
    store = CareStore()
    system = Actor("scribe", "clinic-a", Role.SYSTEM)
    patient = Actor("patient-1", "clinic-a", Role.PATIENT)
    other_staff = Actor("staff-b", "clinic-b", Role.STAFF)
    raw_ai = store.add_entry(system, entry_type="ai_patient_session_summary", content="Raw AI scribe source.")

    assert can_read_entry(patient, raw_ai) is False
    with pytest.raises(AuthorizationError):
        require_same_clinic(other_staff, "clinic-a")
