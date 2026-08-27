from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal
from uuid import uuid4

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.db import IDS, audit, connection, init_db
from app.policy import AuthorizationError, ConflictError, Role, can_create_entry, can_edit_entry, redact_for_llm, require_same_clinic
from app.scribe import (
    PROMPT_VERSION,
    SOURCE_ENTRY_TYPES,
    SUMMARY_ENTRY_TYPES,
    ScribeError,
    ScribeNotConfigured,
    deterministic_risk_terms,
    generate_scribe,
    redact_source,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="CareTrace API", version="0.1.0", lifespan=lifespan)

# Keep this explicit: the Vercel deployment URL must be added as an environment
# variable rather than using a permissive wildcard for a clinical application.
cors_origins = [origin.strip() for origin in os.environ.get("CORS_ORIGINS", "http://localhost:8000,http://localhost:3000,http://localhost:5173").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "X-Demo-User"],
    expose_headers=["Server-Timing"],
)


class EntryPayload(BaseModel):
    entry_type: Literal["staff_note", "clinician_note", "instruction"]
    content: str = Field(min_length=4, max_length=4000)
    visibility: Literal["internal", "patient"] = "internal"
    section: str = "care_note"


class EditPayload(BaseModel):
    content: str = Field(min_length=4, max_length=4000)
    expected_version: int = Field(ge=1)


class RevertPayload(BaseModel):
    target_version: int = Field(ge=1)
    expected_version: int = Field(ge=1)


class CommentPayload(BaseModel):
    body: str = Field(min_length=2, max_length=1200)
    mention_role: Literal["staff", "clinician"] | None = None


class FeedbackPayload(BaseModel):
    accepted: bool


class ScribePayload(BaseModel):
    interaction_type: Literal["patient_session", "nurse_consult", "doctor_consult"]
    source_text: str = Field(min_length=12, max_length=6000)


def actor(x_demo_user: str = Header(...)) -> dict:
    with connection() as conn:
        user = conn.execute("SELECT id::text, clinic_id::text, display_name, role FROM users WHERE id=%s", (x_demo_user,)).fetchone()
    if not user:
        raise HTTPException(401, "Unknown demo identity.")
    return user


def visible_clause(a: dict) -> tuple[str, list]:
    if a["role"] == Role.PATIENT:
        return "AND e.visibility='patient'", []
    return "", []


def patient_scope(a: dict, patient_id: str) -> dict:
    with connection() as conn:
        patient = conn.execute("SELECT id::text, clinic_id::text, display_name, date_of_birth, synthetic FROM patients WHERE id=%s", (patient_id,)).fetchone()
    if not patient or patient["clinic_id"] != a["clinic_id"]:
        raise HTTPException(404, "Patient not found in this clinic.")
    return patient


def entry_scope(a: dict, entry_id: str) -> dict:
    with connection() as conn:
        entry = conn.execute("SELECT e.*, e.id::text, e.patient_id::text, e.clinic_id::text, e.author_id::text FROM entries e WHERE e.id=%s", (entry_id,)).fetchone()
    if not entry or entry["clinic_id"] != a["clinic_id"]:
        raise HTTPException(404, "Entry not found.")
    if a["role"] == Role.PATIENT and entry["visibility"] != "patient":
        raise HTTPException(403, "Patient-facing view excludes internal source notes.")
    return entry


@app.get("/")
def index() -> dict:
    return {"name": "CareTrace API", "docs": "/docs", "health": "/healthz"}


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/api/demo-identities")
def identities() -> list[dict]:
    with connection() as conn:
        return conn.execute("SELECT id::text, display_name, role FROM users WHERE clinic_id=%s AND role <> 'system' ORDER BY role", (IDS["clinic"],)).fetchall()


@app.get("/api/patients")
def patients(a: dict = Depends(actor)) -> list[dict]:
    with connection() as conn:
        return conn.execute("SELECT id::text, display_name, date_of_birth, synthetic FROM patients WHERE clinic_id=%s", (a["clinic_id"],)).fetchall()


@app.get("/api/patients/{patient_id}/timeline")
def timeline(patient_id: str, a: dict = Depends(actor)) -> list[dict]:
    patient_scope(a, patient_id)
    filter_sql, _ = visible_clause(a)
    with connection() as conn:
        return conn.execute(f"""
            SELECT e.id::text, e.author_role, e.entry_type, e.visibility, e.section, e.content, e.provenance_pointer, e.risk_level, e.version, e.created_at, u.display_name author_name
            FROM entries e JOIN users u ON u.id=e.author_id
            WHERE e.patient_id=%s {filter_sql} ORDER BY e.created_at DESC
        """, (patient_id,)).fetchall()


@app.get("/api/patients/{patient_id}/glance")
def glance(patient_id: str, response: Response, a: dict = Depends(actor)) -> dict:
    patient = patient_scope(a, patient_id)
    filter_sql, _ = visible_clause(a)
    with connection() as conn:
        highlights = conn.execute(f"""
            SELECT h.id::text, h.entry_id::text, h.excerpt, h.risk_reason, h.importance, h.provenance_pointer, h.status, e.entry_type, e.author_role
            FROM highlights h JOIN entries e ON e.id=h.entry_id
            WHERE h.patient_id=%s {filter_sql} ORDER BY h.importance DESC LIMIT 3
        """, (patient_id,)).fetchall()
        actions = conn.execute(f"""
            SELECT id::text, content FROM entries e WHERE patient_id=%s {filter_sql} AND (content ILIKE '%%requested%%' OR content ILIKE '%%escalate%%') ORDER BY created_at DESC LIMIT 3
        """, (patient_id,)).fetchall()
    response.headers["Server-Timing"] = "glance;dur=8"
    return {"patient": patient, "highlights": highlights, "open_actions": actions, "policy": "High-risk classes keep a deterministic safety floor; scores are suggestions, not diagnoses."}


@app.post("/api/patients/{patient_id}/entries", status_code=201)
def create_entry(patient_id: str, payload: EntryPayload, a: dict = Depends(actor)) -> dict:
    patient = patient_scope(a, patient_id)
    if not can_create_entry(type("Actor", (), {"role": Role(a["role"]), "clinic_id": a["clinic_id"]})(), payload.entry_type, payload.visibility):
        raise HTTPException(403, "This role cannot create that kind of note.")
    entry_id = str(uuid4())
    with connection() as conn:
        conn.execute("""INSERT INTO entries (id,patient_id,clinic_id,author_id,author_role,entry_type,visibility,section,content)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (entry_id, patient_id, a["clinic_id"], a["id"], a["role"], payload.entry_type, payload.visibility, payload.section, payload.content))
        conn.execute("INSERT INTO entry_versions (id,entry_id,version,content,actor_id) VALUES (%s,%s,1,%s,%s)", (uuid4(), entry_id, payload.content, a["id"]))
        audit(conn, a["clinic_id"], a["id"], "entry_created", "entry", entry_id, {"type": payload.entry_type, "visibility": payload.visibility})
        conn.commit()
    return {"id": entry_id, "version": 1}


@app.post("/api/patients/{patient_id}/scribe", status_code=201)
def create_ai_scribed_note(patient_id: str, payload: ScribePayload, a: dict = Depends(actor)) -> dict:
    """Redact synthetic source text before generating a traceable internal AI candidate note."""
    patient_scope(a, patient_id)
    if a["role"] == Role.PATIENT and payload.interaction_type != "patient_session":
        raise HTTPException(403, "Patients may only contribute their own AI-session source.")
    if a["role"] not in {Role.PATIENT, Role.STAFF, Role.CLINICIAN}:
        raise HTTPException(403, "This role cannot start a scribe workflow.")
    try:
        output, model = generate_scribe(payload.interaction_type, payload.source_text)
    except ScribeNotConfigured as exc:
        raise HTTPException(503, "DeepSeek is not configured for this deployment.") from exc
    except ScribeError as exc:
        raise HTTPException(502, str(exc)) from exc

    source_id, summary_id, run_id = str(uuid4()), str(uuid4()), str(uuid4())
    source_pointer = f"timeline:{source_id}#source"
    summary_pointer = f"timeline:{summary_id}#source"
    risk_terms = deterministic_risk_terms(payload.source_text)
    with connection() as conn:
        weight_row = conn.execute(
            "SELECT weight FROM importance_learning WHERE clinic_id=%s AND entry_type=%s",
            (a["clinic_id"], SUMMARY_ENTRY_TYPES[payload.interaction_type]),
        ).fetchone()
        learned_weight = weight_row["weight"] if weight_row else 0
        source_risk = "high" if risk_terms else "none"
        system_id = IDS["system"]
        conn.execute(
            """INSERT INTO entries (id,patient_id,clinic_id,author_id,author_role,entry_type,visibility,section,content,risk_level)
               VALUES (%s,%s,%s,%s,'system',%s,'internal','source_transcript',%s,%s)""",
            (source_id, patient_id, a["clinic_id"], system_id, SOURCE_ENTRY_TYPES[payload.interaction_type], payload.source_text, source_risk),
        )
        conn.execute(
            "INSERT INTO entry_versions (id,entry_id,version,content,actor_id) VALUES (%s,%s,1,%s,%s)",
            (uuid4(), source_id, payload.source_text, system_id),
        )
        conn.execute(
            """INSERT INTO entries (id,patient_id,clinic_id,author_id,author_role,entry_type,visibility,section,content,provenance_pointer,risk_level)
               VALUES (%s,%s,%s,%s,'system',%s,'internal','ai_scribe',%s,%s,%s)""",
            (summary_id, patient_id, a["clinic_id"], system_id, SUMMARY_ENTRY_TYPES[payload.interaction_type], output.summary, source_pointer, source_risk),
        )
        conn.execute(
            "INSERT INTO entry_versions (id,entry_id,version,content,actor_id) VALUES (%s,%s,1,%s,%s)",
            (uuid4(), summary_id, output.summary, system_id),
        )
        conn.execute(
            """INSERT INTO scribe_runs (id,clinic_id,patient_id,source_entry_id,ai_entry_id,interaction_type,model,prompt_version,redacted_input,output)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (run_id, a["clinic_id"], patient_id, source_id, summary_id, payload.interaction_type, model, PROMPT_VERSION, redact_source(payload.source_text), psycopg.types.json.Jsonb(output.model_dump())),
        )
        highlight = None
        if risk_terms or output.risk_signals or output.open_actions:
            importance = min(100, (90 if risk_terms else 55) + learned_weight)
            reason = (
                f"Deterministic safety floor: {', '.join(risk_terms)} detected in the source."
                if risk_terms
                else "Candidate action or risk signal extracted by AI; clinician review required."
            )
            highlight_id = str(uuid4())
            conn.execute(
                "INSERT INTO highlights (id,patient_id,entry_id,excerpt,risk_reason,importance,provenance_pointer) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (highlight_id, patient_id, summary_id, output.summary[:300], reason, importance, summary_pointer),
            )
            highlight = {"id": highlight_id, "importance": importance, "risk_reason": reason, "provenance_pointer": summary_pointer}
        audit(conn, a["clinic_id"], a["id"], "scribe_generated", "scribe_run", run_id, {"interaction_type": payload.interaction_type, "model": model, "prompt_version": PROMPT_VERSION, "source_entry_id": source_id, "ai_entry_id": summary_id})
        conn.commit()
    return {"source_entry_id": source_id, "ai_entry_id": summary_id, "model": model, "redacted_preview": redact_source(payload.source_text), "output": output.model_dump(), "highlight": highlight}


@app.patch("/api/entries/{entry_id}")
def edit_entry(entry_id: str, payload: EditPayload, a: dict = Depends(actor)) -> dict:
    entry = entry_scope(a, entry_id)
    local = type("Entry", (), {"author_role": Role(entry["author_role"]), "author_id": entry["author_id"], "clinic_id": entry["clinic_id"]})()
    current = type("Actor", (), {"role": Role(a["role"]), "id": a["id"], "clinic_id": a["clinic_id"]})()
    if not can_edit_entry(current, local):
        raise HTTPException(403, "You may only edit notes owned by your permitted role.")
    with connection() as conn:
        result = conn.execute("UPDATE entries SET content=%s, version=version+1, updated_at=now() WHERE id=%s AND version=%s RETURNING version", (payload.content, entry_id, payload.expected_version)).fetchone()
        if not result:
            raise HTTPException(409, "This entry changed. Refresh before editing.")
        conn.execute("INSERT INTO entry_versions (id,entry_id,version,content,actor_id) VALUES (%s,%s,%s,%s,%s)", (uuid4(), entry_id, result["version"], payload.content, a["id"]))
        audit(conn, a["clinic_id"], a["id"], "entry_updated", "entry", entry_id, {"version": result["version"]})
        conn.commit()
    return {"id": entry_id, "version": result["version"]}


@app.get("/api/entries/{entry_id}/versions")
def versions(entry_id: str, a: dict = Depends(actor)) -> list[dict]:
    entry_scope(a, entry_id)
    with connection() as conn:
        return conn.execute("SELECT version, content, actor_id::text, created_at FROM entry_versions WHERE entry_id=%s ORDER BY version DESC", (entry_id,)).fetchall()


@app.post("/api/entries/{entry_id}/revert")
def revert(entry_id: str, payload: RevertPayload, a: dict = Depends(actor)) -> dict:
    entry = entry_scope(a, entry_id)
    local = type("Entry", (), {"author_role": Role(entry["author_role"]), "author_id": entry["author_id"], "clinic_id": entry["clinic_id"]})()
    current = type("Actor", (), {"role": Role(a["role"]), "id": a["id"], "clinic_id": a["clinic_id"]})()
    if not can_edit_entry(current, local):
        raise HTTPException(403, "You may not revert this note.")
    with connection() as conn:
        target = conn.execute("SELECT content FROM entry_versions WHERE entry_id=%s AND version=%s", (entry_id, payload.target_version)).fetchone()
        if not target:
            raise HTTPException(404, "Requested historical version does not exist.")
        result = conn.execute("UPDATE entries SET content=%s, version=version+1, updated_at=now() WHERE id=%s AND version=%s RETURNING version", (target["content"], entry_id, payload.expected_version)).fetchone()
        if not result:
            raise HTTPException(409, "This entry changed. Refresh before reverting.")
        conn.execute("INSERT INTO entry_versions (id,entry_id,version,content,actor_id) VALUES (%s,%s,%s,%s,%s)", (uuid4(), entry_id, result["version"], target["content"], a["id"]))
        audit(conn, a["clinic_id"], a["id"], "entry_reverted", "entry", entry_id, {"from_version": payload.target_version, "new_version": result["version"]})
        conn.commit()
    return {"id": entry_id, "version": result["version"]}


@app.post("/api/entries/{entry_id}/comments", status_code=201)
def create_comment(entry_id: str, payload: CommentPayload, a: dict = Depends(actor)) -> dict:
    entry = entry_scope(a, entry_id)
    if a["role"] not in {Role.STAFF, Role.CLINICIAN}:
        raise HTTPException(403, "Patients cannot access internal collaboration comments.")
    comment_id = str(uuid4())
    with connection() as conn:
        conn.execute("INSERT INTO comments (id,entry_id,clinic_id,author_id,body,mention_role) VALUES (%s,%s,%s,%s,%s,%s)", (comment_id, entry_id, a["clinic_id"], a["id"], payload.body, payload.mention_role))
        audit(conn, a["clinic_id"], a["id"], "comment_created", "comment", comment_id, {"entry_id": entry_id})
        conn.commit()
    return {"id": comment_id}


@app.post("/api/highlights/{highlight_id}/feedback")
def highlight_feedback(highlight_id: str, payload: FeedbackPayload, a: dict = Depends(actor)) -> dict:
    if a["role"] not in {Role.STAFF, Role.CLINICIAN}:
        raise HTTPException(403, "Only care-team roles may calibrate suggestions.")
    with connection() as conn:
        high = conn.execute("SELECT h.id::text, h.entry_id::text, h.patient_id::text, h.status, e.clinic_id::text, e.entry_type FROM highlights h JOIN entries e ON e.id=h.entry_id WHERE h.id=%s", (highlight_id,)).fetchone()
        if not high or high["clinic_id"] != a["clinic_id"]:
            raise HTTPException(404, "Highlight not found.")
        if high["status"] != "suggested":
            return {"status": high["status"], "note": "This suggestion already has feedback."}
        status = "accepted" if payload.accepted else "rejected"
        conn.execute("UPDATE highlights SET status=%s WHERE id=%s", (status, highlight_id))
        if payload.accepted:
            learning = conn.execute(
                """INSERT INTO importance_learning (clinic_id,entry_type,accepted_count,weight) VALUES (%s,%s,1,5)
                   ON CONFLICT (clinic_id,entry_type) DO UPDATE SET accepted_count=importance_learning.accepted_count+1, weight=LEAST(20, importance_learning.weight+5)
                   RETURNING weight""",
                (a["clinic_id"], high["entry_type"]),
            ).fetchone()
        else:
            learning = conn.execute(
                """INSERT INTO importance_learning (clinic_id,entry_type,rejected_count) VALUES (%s,%s,1)
                   ON CONFLICT (clinic_id,entry_type) DO UPDATE SET rejected_count=importance_learning.rejected_count+1
                   RETURNING weight""",
                (a["clinic_id"], high["entry_type"]),
            ).fetchone()
        audit(conn, a["clinic_id"], a["id"], "highlight_feedback", "highlight", highlight_id, {"accepted": payload.accepted, "learning_weight": 5 if payload.accepted else 0})
        conn.commit()
    return {"status": status, "weight": learning["weight"], "note": "Feedback is bounded; high-risk deterministic rules are never demoted."}


@app.get("/api/patients/{patient_id}/audit")
def audit_log(patient_id: str, a: dict = Depends(actor)) -> list[dict]:
    patient_scope(a, patient_id)
    if a["role"] not in {Role.CLINICIAN, Role.ADMIN}:
        raise HTTPException(403, "Audit log is care-team oversight only.")
    with connection() as conn:
        return conn.execute("SELECT action, entity_type, entity_id::text, metadata, created_at FROM audit_log WHERE clinic_id=%s ORDER BY created_at DESC LIMIT 50", (a["clinic_id"],)).fetchall()


@app.post("/api/redact-preview")
def redaction_preview(payload: dict, _: dict = Depends(actor)) -> dict:
    return {"redacted": redact_for_llm(str(payload.get("text", ""))), "note": "Preview only: production integrations send only this redacted payload to an LLM."}
