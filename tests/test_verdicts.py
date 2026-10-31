import json

import httpx

from backend.audit import verdicts
from backend.audit.verdicts import BaselineVerifier, ChatVerifier, Evidence


def _evidence(
    unit_id: str = "alpha:p1:sent1",
    cosine: float = 0.8,
    coverage: float = 0.8,
    numbers: str = "none",
    text: str = "Dense retrieval uses vectors for semantic search.",
) -> Evidence:
    return Evidence(
        unit_id=unit_id,
        paper_key="alpha",
        page=1,
        unit_type="sent",
        parent_id="alpha:p1:para1",
        text=text,
        score=0.60 * cosine + 0.35 * coverage,
        cosine=cosine,
        keyword_coverage=coverage,
        number_status=numbers,
    )


def test_baseline_without_candidates_is_unknown() -> None:
    verdict = BaselineVerifier().verify("claim", "alpha", "Alpha", [])
    assert verdict.verdict == "unknown"
    assert verdict.evidence is None


def test_baseline_conflicting_number_is_unsupported() -> None:
    verdict = BaselineVerifier().verify("claim", "alpha", "Alpha", [_evidence(numbers="conflict")])
    assert (verdict.verdict, verdict.confidence, verdict.review_required) == (
        "unsupported",
        "high",
        False,
    )


def test_baseline_low_similarity_is_unsupported() -> None:
    verdict = BaselineVerifier().verify(
        "claim", "alpha", "Alpha", [_evidence(cosine=0.2, coverage=0.1)]
    )
    assert verdict.verdict == "unsupported"


def test_baseline_missing_number_with_low_similarity_is_unsupported() -> None:
    verdict = BaselineVerifier().verify(
        "claim", "alpha", "Alpha", [_evidence(cosine=0.45, coverage=0.7, numbers="missing")]
    )
    assert verdict.verdict == "unsupported"
    assert "数字" in verdict.reason


def test_baseline_strong_match_is_partial_not_supported() -> None:
    verdict = BaselineVerifier().verify("claim", "alpha", "Alpha", [_evidence()])
    assert (verdict.verdict, verdict.confidence, verdict.review_required) == (
        "partial",
        "high",
        True,
    )
    assert "verifier=none" in verdict.reason


def test_baseline_number_match_can_be_strong_partial() -> None:
    verdict = BaselineVerifier().verify(
        "claim", "alpha", "Alpha", [_evidence(cosine=0.7, coverage=0.7, numbers="match")]
    )
    assert verdict.verdict == "partial"
    assert verdict.confidence == "high"


def test_baseline_high_confidence_needs_coverage_or_number_match() -> None:
    partial_coverage = BaselineVerifier().verify(
        "claim", "alpha", "Alpha", [_evidence(cosine=0.9, coverage=0.58)]
    )
    exact_number = BaselineVerifier().verify(
        "claim", "alpha", "Alpha", [_evidence(cosine=0.75, coverage=0.5, numbers="match")]
    )
    assert (partial_coverage.verdict, partial_coverage.confidence) == ("partial", "medium")
    assert (exact_number.verdict, exact_number.confidence) == ("partial", "high")


def test_baseline_medium_and_weak_evidence() -> None:
    medium = BaselineVerifier().verify(
        "claim", "alpha", "Alpha", [_evidence(cosine=0.55, coverage=0.3)]
    )
    weak = BaselineVerifier().verify(
        "claim", "alpha", "Alpha", [_evidence(cosine=0.40, coverage=0.25)]
    )
    assert (medium.verdict, medium.confidence) == ("partial", "medium")
    assert (weak.verdict, weak.confidence) == ("unknown", "low")


def test_chat_verifier_parses_valid_response(monkeypatch) -> None:
    verifier = ChatVerifier("openai", "test-model", "secret")
    candidate = _evidence()
    monkeypatch.setattr(
        verifier,
        "_request",
        lambda prompt: json.dumps(
            {
                "verdict": "supported",
                "confidence": "high",
                "evidence_id": candidate.unit_id,
                "reason": "direct quote",
            }
        ),
    )
    verdict = verifier.verify("claim", "alpha", "Alpha", [candidate])
    assert (verdict.verdict, verdict.confidence, verdict.evidence) == (
        "supported",
        "high",
        candidate,
    )
    assert verdict.review_required is False


def test_chat_verifier_rejects_invalid_evidence_id(monkeypatch) -> None:
    verifier = ChatVerifier("openai", "test-model", "secret")
    monkeypatch.setattr(
        verifier,
        "_request",
        lambda prompt: json.dumps(
            {
                "verdict": "supported",
                "confidence": "high",
                "evidence_id": "not-a-candidate",
                "reason": "x",
            }
        ),
    )
    verdict = verifier.verify("claim", "alpha", "Alpha", [_evidence()])
    assert verdict.verdict == "unknown"
    assert "候选证据" in verdict.reason


def test_chat_verifier_handles_bad_json_and_http_error(monkeypatch) -> None:
    verifier = ChatVerifier("openai", "test-model", "secret")
    monkeypatch.setattr(verifier, "_request", lambda prompt: "not json")
    assert verifier.verify("claim", "alpha", "Alpha", [_evidence()]).verdict == "unknown"

    def boom(prompt: str) -> str:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(verifier, "_request", boom)
    verdict = verifier.verify("claim", "alpha", "Alpha", [_evidence()])
    assert verdict.verdict == "unknown"
    assert "请求失败" in verdict.reason


def test_chat_verifier_does_not_call_model_without_candidates(monkeypatch) -> None:
    verifier = ChatVerifier("openai", "test-model", "secret")

    def fail(prompt: str) -> str:
        raise AssertionError("model must not be called")

    monkeypatch.setattr(verifier, "_request", fail)
    assert verifier.verify("claim", "alpha", "Alpha", []).verdict == "unknown"


def test_openai_request_shape(monkeypatch) -> None:
    captured = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"verdict":"unknown"}'}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(verdicts.httpx, "post", fake_post)
    verifier = ChatVerifier("openai", "test-model", "secret", base_url="https://example.test/v1")
    assert verifier._request("prompt") == '{"verdict":"unknown"}'
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["json"]["model"] == "test-model"


def test_anthropic_request_shape(monkeypatch) -> None:
    captured = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"content": [{"type": "text", "text": "ok"}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(verdicts.httpx, "post", fake_post)
    verifier = ChatVerifier(
        "anthropic", "test-model", "secret", base_url="https://example.test"
    )
    assert verifier._request("prompt") == "ok"
    assert captured["url"] == "https://example.test/v1/messages"
    assert captured["headers"]["x-api-key"] == "secret"
    assert captured["json"]["max_tokens"] == 600
