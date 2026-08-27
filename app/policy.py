from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from re import sub
from uuid import uuid4


class Role(StrEnum):
    PATIENT = "patient"
    STAFF = "staff"
    CLINICIAN = "clinician"
    ADMIN = "admin"
    SYSTEM = "system"


class AuthorizationError(PermissionError):
    pass


class ConflictError(RuntimeError):
    pass


def require_same_clinic(actor: "Actor", clinic_id: str) -> None:
    if actor.role != Role.SYSTEM and actor.clinic_id != clinic_id:
        raise AuthorizationError("Cross-clinic access is forbidden.")


def can_read_entry(actor: "Actor", entry: "Entry") -> bool:
    if actor.role == Role.SYSTEM:
        return True
    if actor.clinic_id != entry.clinic_id:
        return False
    if actor.role == Role.PATIENT:
        return entry.visibility == "patient"
    return True


def can_create_entry(actor: "Actor", entry_type: str, visibility: str) -> bool:
    if actor.role == Role.STAFF:
        return entry_type == "staff_note" and visibility == "internal"
    if actor.role == Role.CLINICIAN:
        return entry_type in {"clinician_note", "instruction"} and visibility in {"internal", "patient"}
    if actor.role == Role.SYSTEM:
        return entry_type.startswith("ai_")
    return False


def can_edit_entry(actor: "Actor", entry: "Entry") -> bool:
    if actor.role == Role.ADMIN:
        return False  # oversight is deliberately read-only in this prototype
    if actor.role == Role.CLINICIAN:
        return entry.author_role == Role.CLINICIAN and actor.clinic_id == entry.clinic_id
    if actor.role == Role.STAFF:
        return entry.author_role == Role.STAFF and entry.author_id == actor.id and actor.clinic_id == entry.clinic_id
    return False


def redact_for_llm(text: str) -> str:
    """Defence-in-depth redaction before external model invocation; synthetic data remains required."""
    text = sub(r"\b(?:S?\d{7}[A-Z]|\d{3}-\d{2}-\d{4})\b", "[REDACTED_ID]", text, flags=0)
    text = sub(r"\b(?:\+?65[ -]?)?\d{4}[ -]?\d{4}\b", "[REDACTED_PHONE]", text)
    text = sub(r"\b(?:Mr|Mrs|Ms|Dr)\.\s+[A-Z][a-z]+\b", "[REDACTED_NAME]", text)
    return text


@dataclass(frozen=True)
class Actor:
    id: str
    clinic_id: str
    role: Role


@dataclass
class Entry:
    id: str
    clinic_id: str
    author_id: str
    author_role: Role
    entry_type: str
    visibility: str
    section: str
    content: str
    provenance_pointer: str | None = None
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Highlight:
    id: str
    entry_id: str
    excerpt: str
    risk_reason: str
    importance: int
    provenance_pointer: str
    accepted: bool | None = None


class CareStore:
    """Small deterministic model used by tests and mirrors the production policy."""

    def __init__(self) -> None:
        self.entries: dict[str, Entry] = {}
        self.versions: dict[str, list[dict]] = {}
        self.audit: list[dict] = []
        self.highlights: dict[str, Highlight] = {}
        self.feedback_weight: dict[str, int] = {}

    def add_entry(self, actor: Actor, *, entry_type: str, content: str, section: str = "care_note", visibility: str = "internal", provenance_pointer: str | None = None) -> Entry:
        if not can_create_entry(actor, entry_type, visibility):
            raise AuthorizationError(f"{actor.role} cannot create {entry_type}.")
        entry = Entry(str(uuid4()), actor.clinic_id, actor.id, actor.role, entry_type, visibility, section, content, provenance_pointer)
        self.entries[entry.id] = entry
        self.versions[entry.id] = [{"version": 1, "content": content, "actor_id": actor.id}]
        self.audit.append({"action": "entry_created", "entry_id": entry.id, "actor_id": actor.id, "metadata_only": True})
        return entry

    def edit(self, actor: Actor, entry_id: str, content: str, expected_version: int) -> Entry:
        entry = self.entries[entry_id]
        require_same_clinic(actor, entry.clinic_id)
        if not can_edit_entry(actor, entry):
            raise AuthorizationError("Role cannot edit this entry.")
        if entry.version != expected_version:
            raise ConflictError("Version mismatch; refresh and retry.")
        entry.content, entry.version = content, entry.version + 1
        self.versions[entry_id].append({"version": entry.version, "content": content, "actor_id": actor.id})
        self.audit.append({"action": "entry_updated", "entry_id": entry.id, "actor_id": actor.id, "metadata_only": True})
        return entry

    def revert(self, actor: Actor, entry_id: str, target_version: int, expected_version: int) -> Entry:
        entry = self.entries[entry_id]
        if not can_edit_entry(actor, entry):
            raise AuthorizationError("Role cannot revert this entry.")
        target = next((v for v in self.versions[entry_id] if v["version"] == target_version), None)
        if target is None:
            raise ValueError("Version not found.")
        reverted = self.edit(actor, entry_id, target["content"], expected_version)
        self.audit.append({"action": "entry_reverted", "entry_id": entry.id, "actor_id": actor.id, "metadata_only": True})
        return reverted

    def create_highlight(self, entry_id: str, excerpt: str, reason: str) -> Highlight:
        entry = self.entries[entry_id]
        keywords = tuple(k for k in ("allergy", "anaphyl", "chest pain", "urgent", "overdue") if k in entry.content.lower())
        importance = 40 + (40 if keywords else 0) + self.feedback_weight.get(entry.entry_type, 0)
        pointer = f"timeline:{entry.id}#source"
        highlight = Highlight(str(uuid4()), entry.id, excerpt, reason, min(100, importance), pointer)
        self.highlights[highlight.id] = highlight
        return highlight

    def record_feedback(self, highlight_id: str, accepted: bool) -> None:
        highlight = self.highlights[highlight_id]
        highlight.accepted = accepted
        if accepted:
            entry = self.entries[highlight.entry_id]
            self.feedback_weight[entry.entry_type] = min(20, self.feedback_weight.get(entry.entry_type, 0) + 5)

    def resolve_provenance(self, pointer: str) -> Entry | None:
        if not pointer.startswith("timeline:"):
            return None
        return self.entries.get(pointer.split(":", 1)[1].split("#", 1)[0])
