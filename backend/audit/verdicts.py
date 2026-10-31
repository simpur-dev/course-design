from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

VERDICTS = ("supported", "partial", "unsupported", "unknown")
CONFIDENCES = ("high", "medium", "low")


@dataclass(frozen=True)
class Evidence:
    unit_id: str
    paper_key: str
    page: int
    unit_type: str
    parent_id: str
    text: str
    score: float
    cosine: float
    keyword_coverage: float
    number_status: str


@dataclass(frozen=True)
class Verdict:
    verdict: str
    confidence: str
    review_required: bool
    reason: str
    evidence: Evidence | None


class Verifier(Protocol):
    name: str

    def verify(
        self,
        claim: str,
        paper_key: str,
        paper_title: str,
        candidates: Sequence[Evidence],
    ) -> Verdict: ...


class BaselineVerifier:
    """No-key extractive baseline. It never emits ``supported``."""

    name = "none/baseline"

    def verify(
        self,
        claim: str,
        paper_key: str,
        paper_title: str,
        candidates: Sequence[Evidence],
    ) -> Verdict:
        if not candidates:
            return Verdict(
                verdict="unknown",
                confidence="low",
                review_required=True,
                reason="被引论文内未检索到候选证据，无法判断",
                evidence=None,
            )
        best = max(candidates, key=lambda candidate: (candidate.score, candidate.cosine))
        cosine = best.cosine
        coverage = best.keyword_coverage
        numbers = best.number_status
        quote = f"p{best.page} `{best.unit_id}`"

        if numbers == "conflict":
            return Verdict(
                verdict="unsupported",
                confidence="high",
                review_required=False,
                reason=f"证据 {quote} 中的数字与主张冲突",
                evidence=best,
            )
        if cosine < 0.35 and coverage < 0.35:
            return Verdict(
                verdict="unsupported",
                confidence="medium",
                review_required=False,
                reason=(
                    f"被引论文内最佳证据 {quote} 语义相关度 {cosine:.2f}、"
                    f"关键词覆盖 {coverage:.0%}，未找到支持该主张的内容"
                ),
                evidence=best,
            )
        if numbers == "missing" and cosine < 0.55:
            return Verdict(
                verdict="unsupported",
                confidence="medium",
                review_required=False,
                reason=f"被引论文最佳证据 {quote} 缺少主张的关键数字，且语义相关度仅 {cosine:.2f}",
                evidence=best,
            )
        if (cosine >= 0.62 and coverage >= 0.65 and numbers in {"none", "match"}) or (
            numbers == "match" and cosine >= 0.70 and coverage >= 0.45
        ):
            return Verdict(
                verdict="partial",
                confidence="high",
                review_required=True,
                reason=(
                    f"证据 {quote} 与主张高度吻合（语义 {cosine:.2f}、覆盖 {coverage:.0%}），"
                    "但 verifier=none 不出具 supported 结论，请人工确认"
                ),
                evidence=best,
            )
        if cosine >= 0.50 or coverage >= 0.40:
            return Verdict(
                verdict="partial",
                confidence="medium",
                review_required=True,
                reason=(
                    f"证据 {quote} 部分相关（语义 {cosine:.2f}、覆盖 {coverage:.0%}），"
                    "关键限定或数字仍需人工确认"
                ),
                evidence=best,
            )
        return Verdict(
            verdict="unknown",
            confidence="low",
            review_required=True,
            reason=f"证据 {quote} 相关性不足（语义 {cosine:.2f}、覆盖 {coverage:.0%}），无法判断",
            evidence=best,
        )


class ChatVerifier:
    """OpenAI-compatible or Anthropic chat adapter; only used when explicitly configured."""

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        if provider not in {"openai", "anthropic"}:
            raise ValueError("provider must be 'openai' or 'anthropic'")
        if not api_key:
            raise ValueError("api_key is required")
        if not model:
            raise ValueError("model is required")
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.name = f"{provider}:{model}"

    def verify(
        self,
        claim: str,
        paper_key: str,
        paper_title: str,
        candidates: Sequence[Evidence],
    ) -> Verdict:
        if not candidates:
            return Verdict(
                verdict="unknown",
                confidence="low",
                review_required=True,
                reason="被引论文内未检索到候选证据，未调用模型",
                evidence=None,
            )
        prompt = _build_prompt(claim, paper_key, paper_title, candidates)
        try:
            content = self._request(prompt)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return Verdict(
                verdict="unknown",
                confidence="low",
                review_required=True,
                reason=f"verifier 请求失败：{type(exc).__name__}: {exc}",
                evidence=candidates[0],
            )
        return _parse_verdict(content, candidates)

    def _request(self, prompt: str) -> str:
        if self.provider == "openai":
            base = (self.base_url or "https://api.openai.com/v1").rstrip("/")
            response = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You audit citations. Reply with one JSON object only.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            return str(payload["choices"][0]["message"]["content"])

        base = (self.base_url or "https://api.anthropic.com").rstrip("/")
        response = httpx.post(
            f"{base}/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": self.model,
                "max_tokens": 600,
                "temperature": 0,
                "system": "You audit citations. Reply with one JSON object only.",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        for block in payload["content"]:
            if block.get("type") == "text":
                return str(block["text"])
        raise ValueError("anthropic response has no text block")


def _build_prompt(
    claim: str,
    paper_key: str,
    paper_title: str,
    candidates: Sequence[Evidence],
) -> str:
    evidence = [
        {"evidence_id": candidate.unit_id, "page": candidate.page, "text": candidate.text}
        for candidate in candidates[:8]
    ]
    return (
        "Audit whether the cited paper supports the claim using only the evidence candidates.\n"
        "Verdicts: supported (direct entailment), partial (weak or qualified support), "
        "unsupported (contradiction or no support in the paper), unknown (evidence insufficient).\n"
        "Pick evidence_id only from the candidates. For supported/partial, that evidence must "
        "contain the quoted support. Return JSON with keys: verdict, confidence (high|medium|low), "
        "evidence_id, reason. Do not add prose outside JSON.\n\n"
        f"Cited paper: {json.dumps({'key': paper_key, 'title': paper_title}, ensure_ascii=False)}\n"
        f"Claim: {json.dumps(claim, ensure_ascii=False)}\n"
        f"Candidates: {json.dumps(evidence, ensure_ascii=False)}"
    )


def _parse_verdict(content: str, candidates: Sequence[Evidence]) -> Verdict:
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        return Verdict(
            verdict="unknown",
            confidence="low",
            review_required=True,
            reason="verifier 返回内容不是 JSON",
            evidence=candidates[0],
        )
    try:
        payload: dict[str, Any] = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return Verdict(
            verdict="unknown",
            confidence="low",
            review_required=True,
            reason="verifier 返回的 JSON 无法解析",
            evidence=candidates[0],
        )

    verdict = str(payload.get("verdict", "")).lower()
    confidence = str(payload.get("confidence", "")).lower()
    if verdict not in VERDICTS:
        verdict = "unknown"
    if confidence not in CONFIDENCES:
        confidence = "low"
    evidence_id = str(payload.get("evidence_id", ""))
    evidence = next(
        (candidate for candidate in candidates if candidate.unit_id == evidence_id),
        None,
    )
    if verdict in {"supported", "partial"} and evidence is None:
        return Verdict(
            verdict="unknown",
            confidence="low",
            review_required=True,
            reason="verifier 结论未引用候选证据 id，按 unknown 处理",
            evidence=candidates[0],
        )
    reason = re.sub(r"\s+", " ", str(payload.get("reason", ""))).strip()
    if not reason:
        reason = "verifier 未给出理由"
    return Verdict(
        verdict=verdict,
        confidence=confidence,
        review_required=verdict in {"partial", "unknown"},
        reason=reason[:1000],
        evidence=evidence or candidates[0],
    )
