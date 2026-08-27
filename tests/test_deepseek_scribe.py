import json

from app.scribe import build_messages, deterministic_risk_terms, generate_scribe


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_deepseek_scribe_redacts_before_request_and_validates_json_contract():
    messages = build_messages("nurse_consult", "Dr. Tan called +65 9123 4567 about S1234567A.")
    sent = messages[-1]["content"]
    assert "Dr. Tan" not in sent
    assert "+65 9123 4567" not in sent
    assert "S1234567A" not in sent
    assert "[REDACTED_NAME]" in sent
    assert "[REDACTED_PHONE]" in sent
    assert "[REDACTED_ID]" in sent

    captured = {}

    def opener(request, timeout):
        captured["body"] = json.loads(request.data.decode())
        return FakeResponse({"choices": [{"message": {"content": json.dumps({"summary": "Nurse source recorded; clinician review requested.", "candidate_facts": ["Follow-up requested"], "open_actions": ["Review follow-up"], "risk_signals": [], "abstain_reason": None})}}]})

    output, model = generate_scribe("nurse_consult", "Dr. Tan called +65 9123 4567 about S1234567A.", api_key="test-key", request_opener=opener)
    assert model == "deepseek-v4-flash"
    assert output.open_actions == ["Review follow-up"]
    assert "Dr. Tan" not in captured["body"]["messages"][1]["content"]
    assert captured["body"]["response_format"] == {"type": "json_object"}


def test_deterministic_safety_terms_do_not_depend_on_model_labels():
    assert deterministic_risk_terms("Patient reports hives and shortness of breath with penicillin.") == ["allergy", "breathing concern"]
