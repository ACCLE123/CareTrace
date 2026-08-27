from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://caretrace:caretrace_dev_only@localhost:5432/caretrace")

SCHEMA = """
CREATE TABLE IF NOT EXISTS clinics (id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE IF NOT EXISTS users (id uuid PRIMARY KEY, clinic_id uuid NOT NULL REFERENCES clinics(id), display_name text NOT NULL, role text NOT NULL CHECK (role IN ('patient','staff','clinician','admin','system')));
CREATE TABLE IF NOT EXISTS patients (id uuid PRIMARY KEY, clinic_id uuid NOT NULL REFERENCES clinics(id), display_name text NOT NULL, date_of_birth date, synthetic boolean NOT NULL DEFAULT true);
CREATE TABLE IF NOT EXISTS entries (
  id uuid PRIMARY KEY, patient_id uuid NOT NULL REFERENCES patients(id), clinic_id uuid NOT NULL REFERENCES clinics(id), author_id uuid NOT NULL REFERENCES users(id), author_role text NOT NULL,
  entry_type text NOT NULL, visibility text NOT NULL CHECK (visibility IN ('internal','patient')), section text NOT NULL DEFAULT 'care_note', content text NOT NULL,
  provenance_pointer text, risk_level text NOT NULL DEFAULT 'none', version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS entry_versions (id uuid PRIMARY KEY, entry_id uuid NOT NULL REFERENCES entries(id), version integer NOT NULL, content text NOT NULL, actor_id uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(entry_id, version));
CREATE TABLE IF NOT EXISTS comments (id uuid PRIMARY KEY, entry_id uuid NOT NULL REFERENCES entries(id), clinic_id uuid NOT NULL REFERENCES clinics(id), author_id uuid NOT NULL REFERENCES users(id), body text NOT NULL, mention_role text, resolved boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS clinical_conflicts (
  id uuid PRIMARY KEY, clinic_id uuid NOT NULL REFERENCES clinics(id), patient_id uuid NOT NULL REFERENCES patients(id),
  newer_entry_id uuid NOT NULL REFERENCES entries(id), prior_entry_id uuid NOT NULL REFERENCES entries(id),
  category text NOT NULL CHECK (category IN ('allergy','medication_dose','care_plan')), reason text NOT NULL,
  status text NOT NULL DEFAULT 'needs_clinician_review' CHECK (status IN ('needs_clinician_review','confirmed_new','retained_existing')),
  resolved_by uuid REFERENCES users(id), resolved_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(newer_entry_id, prior_entry_id, category)
);
CREATE TABLE IF NOT EXISTS highlights (id uuid PRIMARY KEY, patient_id uuid NOT NULL REFERENCES patients(id), entry_id uuid NOT NULL REFERENCES entries(id), excerpt text NOT NULL, risk_reason text NOT NULL, importance integer NOT NULL, provenance_pointer text NOT NULL, status text NOT NULL DEFAULT 'suggested', created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS audit_log (id uuid PRIMARY KEY, clinic_id uuid NOT NULL REFERENCES clinics(id), actor_id uuid NOT NULL REFERENCES users(id), action text NOT NULL, entity_type text NOT NULL, entity_id uuid NOT NULL, metadata jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS scribe_runs (
  id uuid PRIMARY KEY, clinic_id uuid NOT NULL REFERENCES clinics(id), patient_id uuid NOT NULL REFERENCES patients(id),
  source_entry_id uuid NOT NULL UNIQUE REFERENCES entries(id), ai_entry_id uuid NOT NULL UNIQUE REFERENCES entries(id),
  interaction_type text NOT NULL CHECK (interaction_type IN ('patient_session','nurse_consult','doctor_consult')),
  model text NOT NULL, prompt_version text NOT NULL, redacted_input text NOT NULL, output jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS importance_learning (
  clinic_id uuid NOT NULL REFERENCES clinics(id), entry_type text NOT NULL,
  accepted_count integer NOT NULL DEFAULT 0, rejected_count integer NOT NULL DEFAULT 0, weight integer NOT NULL DEFAULT 0 CHECK (weight BETWEEN 0 AND 20),
  PRIMARY KEY (clinic_id, entry_type)
);
CREATE INDEX IF NOT EXISTS entries_patient_created_idx ON entries(patient_id, created_at DESC);
CREATE INDEX IF NOT EXISTS conflicts_patient_status_idx ON clinical_conflicts(patient_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS audit_clinic_created_idx ON audit_log(clinic_id, created_at DESC);
CREATE INDEX IF NOT EXISTS scribe_runs_patient_created_idx ON scribe_runs(patient_id, created_at DESC);
"""

IDS = {
    "clinic": "11111111-1111-1111-1111-111111111111",
    "other_clinic": "22222222-2222-2222-2222-222222222222",
    "patient": "33333333-3333-3333-3333-333333333333",
    "clinician": "44444444-4444-4444-4444-444444444444",
    "staff": "55555555-5555-5555-5555-555555555555",
    "patient_user": "66666666-6666-6666-6666-666666666666",
    "admin": "77777777-7777-7777-7777-777777777777",
    "system": "88888888-8888-8888-8888-888888888888",
}


@contextmanager
def connection():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        yield conn


def init_db() -> None:
    with connection() as conn:
        conn.execute(SCHEMA)
        count = conn.execute("SELECT count(*) AS n FROM clinics").fetchone()["n"]
        if count:
            return
        seed(conn)
        conn.commit()


def seed(conn: psycopg.Connection) -> None:
    clinic = UUID(IDS["clinic"])
    conn.execute("INSERT INTO clinics VALUES (%s, %s), (%s, %s)", (clinic, "Nightingale Demo Clinic", UUID(IDS["other_clinic"]), "Other Clinic"))
    users = [
        ("clinician", "Dr. Mira Chen", "clinician"), ("staff", "Nurse Aisha Lim", "staff"), ("patient_user", "Jordan Tan (synthetic)", "patient"), ("admin", "Clinic Admin", "admin"), ("system", "Nightingale Scribe", "system"),
    ]
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO users VALUES (%s, %s, %s, %s)", [(UUID(IDS[key]), clinic, name, role) for key, name, role in users])
    patient = UUID(IDS["patient"])
    conn.execute("INSERT INTO patients VALUES (%s, %s, %s, %s, true)", (patient, clinic, "Jordan Tan — synthetic patient", "1985-09-12"))
    entries = [
        ("2025-04-15T09:00:00+00:00", "staff", "staff_note", "internal", "Medication reconciliation requested before next consult. @clinician", None, "moderate"),
        ("2026-02-06T10:00:00+00:00", "system", "ai_patient_session_summary", "internal", "Patient-reported penicillin allergy: hives and shortness of breath. Wants confirmation before antibiotic prescription.", "session:pre-consult-2026-02-06", "high"),
        ("2026-08-26T08:15:00+00:00", "system", "ai_doctor_consult_summary", "internal", "AI-scribed consult summary: persistent chest discomfort reported. Clinician to evaluate today; no diagnosis generated.", "consult:doctor-2026-08-26", "high"),
        ("2026-08-26T09:00:00+00:00", "clinician", "clinician_note", "internal", "Assessment: reviewed symptoms. ECG and troponin order requested. Escalate if symptoms worsen.", None, "high"),
        ("2026-08-26T09:10:00+00:00", "clinician", "instruction", "patient", "Patient-facing instruction approved by clinician: seek urgent care if chest discomfort worsens or breathing becomes difficult.", None, "high"),
    ]
    for timestamp, user_key, typ, visibility, content, source, risk in entries:
        entry_id = uuid4()
        user_id = UUID(IDS[user_key])
        role = "system" if user_key == "system" else ("staff" if user_key == "staff" else "clinician")
        conn.execute("INSERT INTO entries (id, patient_id, clinic_id, author_id, author_role, entry_type, visibility, content, provenance_pointer, risk_level, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (entry_id, patient, clinic, user_id, role, typ, visibility, content, source, risk, timestamp, timestamp))
        conn.execute("INSERT INTO entry_versions (id, entry_id, version, content, actor_id, created_at) VALUES (%s,%s,1,%s,%s,%s)", (uuid4(), entry_id, content, user_id, timestamp))
        if risk == "high":
            conn.execute("INSERT INTO highlights VALUES (%s,%s,%s,%s,%s,%s,%s,'suggested',%s)", (uuid4(), patient, entry_id, content[:130], "Deterministic safety floor: high-risk tag or explicit escalation language.", 92 if "allergy" in content.lower() else 88, f"timeline:{entry_id}#source", timestamp))


def audit(conn: psycopg.Connection, clinic_id: str, actor_id: str, action: str, entity_type: str, entity_id: str, metadata: dict | None = None) -> None:
    conn.execute("INSERT INTO audit_log (id, clinic_id, actor_id, action, entity_type, entity_id, metadata) VALUES (%s,%s,%s,%s,%s,%s,%s)", (uuid4(), clinic_id, actor_id, action, entity_type, entity_id, psycopg.types.json.Jsonb(metadata or {})))
