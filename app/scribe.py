"""Safety-bounded DeepSeek adapter for synthetic CareTrace scribe demos."""

from __future__ import annotations

import json
import os
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, ValidationError

from app.policy import redact_for_llm


PROMPT_VERSION = "caretrace-scribe-v1"
DEFAULT_MODEL = "deepseek-v4-flash"
SOURCE_TYPES = ("patient_session", "nurse_consult", "doctor_consult")
SOURCE_ENTRY_TYPES = {
    "patient_session": "patient_session_source",
    "nurse_consult": "nurse_consult_source",
    "doctor_consult": "doctor_consult_source",
}
SUMMARY_ENTRY_TYPES = {
    "patient_session": "ai_patient_session_summary",
    "nurse_consult": "ai_nurse_consult_summary",
    "doctor_consult": "ai_doctor_consult_summary",
}


class ScribeError(RuntimeError):
    pass


class ScribeNotConfigured(ScribeError):
    pass


class ScribeOutput(BaseModel):
    """A constrained candidate record, never a diagnosis or patient instruction."""

    summary: str = Field(min_length=1, max_length=1600)
    candidate_facts: list[str] = Field(default_factory=list, max_length=8)
    open_actions: list[str] = Field(default_factory=list, max_length=5)
    risk_signals: list[str] = Field(default_factory=list, max_length=5)
    abstain_reason: str | None = Field(default=None, max_length=400)


def redact_source(text: str) -> str:
    return redact_for_llm(text)


def build_messages(source_type: Literal["patient_session", "nurse_consult", "doctor_consult"], source_text: str) -> list[dict[str, str]]:
    redacted = redact_source(source_text)
    return [
        {
            "role": "system",
            "content": (
                "You are CareTrace's clinical documentation extraction assistant. "
                "Return only valid JSON. Extract only statements supported by the supplied synthetic source. "
                "Do not diagnose, prescribe, infer missing facts, or write patient-facing advice. "
                "If the source is insufficient, use abstain_reason. "
                "Schema: {summary: string, candidate_facts: string[], open_actions: string[], "
                "risk_signals: string[], abstain_reason: string|null}."
            ),
        },
        {
            "role": "user",
            "content": f"Interaction type: {source_type}\nRedacted source:\n{redacted}",
        },
    ]


def parse_model_json(content: str) -> ScribeOutput:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    try:
        return ScribeOutput.model_validate(json.loads(cleaned))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ScribeError("DeepSeek returned an invalid structured scribe response.") from exc


def generate_scribe(
    source_type: Literal["patient_session", "nurse_consult", "doctor_consult"],
    source_text: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    request_opener=urlopen,
) -> tuple[ScribeOutput, str]:
    """Call DeepSeek through its OpenAI-compatible Chat Completions endpoint."""
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise ScribeNotConfigured("DEEPSEEK_API_KEY is not configured.")
    selected_model = model or os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)
    endpoint = (base_url or os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": selected_model,
            "messages": build_messages(source_type, source_text),
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": 700,
            "response_format": {"type": "json_object"},
        }
    ).encode()
    request = Request(endpoint, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    try:
        with request_opener(request, timeout=25) as response:
            payload = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError) as exc:
        raise ScribeError("DeepSeek request failed; no AI note was stored.") from exc
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ScribeError("DeepSeek response did not contain a completion.") from exc
    if not isinstance(content, str):
        raise ScribeError("DeepSeek response content was empty.")
    return parse_model_json(content), selected_model


def deterministic_risk_terms(source_text: str) -> list[str]:
    lower = source_text.lower()
    checks = {
        "allergy": ("allergy", "allergic", "hives"),
        "breathing concern": ("shortness of breath", "breathing becomes difficult"),
        "chest discomfort": ("chest discomfort", "chest pain"),
        "escalation language": ("urgent", "escalate", "emergency"),
    }
    return [label for label, terms in checks.items() if any(term in lower for term in terms)]
