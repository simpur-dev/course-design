from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .bibliography import PaperRef
from .claims import Claim
from .embeddings import EmbeddingCache
from .store import UNIT_MODE, EvidenceStore, HybridHit, PaperRecord
from .terms import NumberMention, extract_keywords, extract_numbers, keyword_coverage, number_status
from .verdicts import Evidence, Verdict, Verifier

_VERDICT_ORDER = {"unsupported": 0, "unknown": 1, "partial": 2, "supported": 3}
ProgressCallback = Callable[[dict[str, Any]], None]


class AuditError(ValueError):
    pass


@dataclass(frozen=True)
class CitationCheck:
    citation: str
    paper: PaperRecord
    verdict: str
    confidence: str
    review_required: bool
    reason: str
    evidence: Evidence | None
    keywords: tuple[str, ...]
    number_status: str
    paragraph_hits: tuple[HybridHit, ...]
    sentence_candidates: tuple[Evidence, ...]
    seconds: float
    error: str | None = None


@dataclass(frozen=True)
class ClaimCheck:
    claim: Claim
    checks: tuple[CitationCheck, ...]
    verdict: str
    seconds: float


@dataclass(frozen=True)
class AuditReport:
    run_id: str
    generated_at: str
    draft_path: str
    bib_path: str
    verifier: str
    embedding_model: str
    claims: tuple[ClaimCheck, ...]
    warnings: tuple[str, ...]
    unit_mode: str = UNIT_MODE

    @property
    def citation_count(self) -> int:
        return sum(len(claim.checks) for claim in self.claims)

    @property
    def citation_verdicts(self) -> dict[str, int]:
        counts = dict.fromkeys(_VERDICT_ORDER, 0)
        for claim in self.claims:
            for check in claim.checks:
                counts[check.verdict] += 1
        return counts

    @property
    def claim_verdicts(self) -> dict[str, int]:
        counts = dict.fromkeys(_VERDICT_ORDER, 0)
        for claim in self.claims:
            counts[claim.verdict] += 1
        return counts

    @property
    def review_count(self) -> int:
        return sum(
            1 for claim in self.claims for check in claim.checks if check.review_required
        )

    @property
    def error_count(self) -> int:
        return sum(1 for claim in self.claims for check in claim.checks if check.error)


class AuditEngine:
    def __init__(
        self,
        store: EvidenceStore,
        cache: EmbeddingCache,
        verifier: Verifier,
        embedding_model: str,
        paragraph_limit: int = 5,
        per_leg: int = 20,
        candidate_limit: int = 8,
    ) -> None:
        self.store = store
        self.cache = cache
        self.verifier = verifier
        self.embedding_model = embedding_model
        self.paragraph_limit = paragraph_limit
        self.per_leg = per_leg
        self.candidate_limit = candidate_limit

    def audit(
        self,
        claims: Sequence[Claim],
        refs: dict[str, PaperRef],
        draft_path: str,
        bib_path: str,
        on_progress: ProgressCallback | None = None,
    ) -> AuditReport:
        papers = self._preflight(claims, refs, bib_path)
        total = len(claims)
        _emit_progress(
            on_progress,
            stage="preflight",
            done=0,
            total=total,
            message="草稿与论文库校验通过",
        )
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        results: list[ClaimCheck] = []
        warnings: list[str] = []
        if self.verifier.name.startswith("none"):
            warnings.append(
                "verifier=none：无 key 基线不出具 supported 结论；supported/partial "
                "均需人工确认。"
            )

        for index, claim in enumerate(claims, start=1):
            _emit_progress(
                on_progress,
                stage="claim",
                done=index - 1,
                total=total,
                claim_id=claim.claim_id,
                message=f"正在核对 {claim.claim_id}（{index}/{total}）",
            )
            start = time.perf_counter()
            query_vector = self.cache.embed([claim.text]).vectors[0]
            keywords = extract_keywords(claim.text)
            numbers = extract_numbers(claim.text)
            if not keywords:
                warnings.append(
                    f"{claim.claim_id}: 未提取到英文关键词，全文检索为空，仅使用向量检索；"
                    "跨语言核对仍需人工复核。"
                )
            checks = tuple(
                self._check_citation(
                    claim,
                    citation,
                    papers[citation],
                    query_vector,
                    keywords,
                    numbers,
                )
                for citation in claim.citations
            )
            results.append(
                ClaimCheck(
                    claim=claim,
                    checks=checks,
                    verdict=_worst_verdict(checks),
                    seconds=time.perf_counter() - start,
                )
            )
            _emit_progress(
                on_progress,
                stage="claim",
                done=index,
                total=total,
                claim_id=claim.claim_id,
                message=f"{claim.claim_id} 完成：{results[-1].verdict}",
            )

        _emit_progress(
            on_progress,
            stage="report",
            done=total,
            total=total,
            message="正在生成报告",
        )
        return AuditReport(
            run_id=run_id,
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            draft_path=draft_path,
            bib_path=bib_path,
            verifier=self.verifier.name,
            embedding_model=self.embedding_model,
            claims=tuple(results),
            warnings=tuple(warnings),
        )

    def _preflight(
        self,
        claims: Sequence[Claim],
        refs: dict[str, PaperRef],
        bib_path: str,
    ) -> dict[str, PaperRecord]:
        cited = {citation for claim in claims for citation in claim.citations}
        unknown = sorted(cited - refs.keys())
        if unknown:
            raise AuditError(
                "draft cites keys missing from bibliography: " + ", ".join(unknown)
            )
        papers: dict[str, PaperRecord] = {}
        missing: list[str] = []
        for key in sorted(cited):
            record = self.store.get_paper(key)
            if record is None:
                missing.append(key)
            else:
                papers[key] = record
        if missing:
            keys = " ".join(f"--key {key}" for key in missing)
            raise AuditError(
                f"papers not ingested: {', '.join(missing)}; "
                f"run: yinju ingest --bib {bib_path} {keys}"
            )
        return papers

    def _check_citation(
        self,
        claim: Claim,
        citation: str,
        paper: PaperRecord,
        query_vector: Sequence[float],
        keywords: tuple[str, ...],
        numbers: tuple[NumberMention, ...],
    ) -> CitationCheck:
        start = time.perf_counter()
        paragraph_hits: tuple[HybridHit, ...] = ()
        candidates: tuple[Evidence, ...] = ()
        try:
            paragraph_hits = tuple(
                self.store.hybrid_search(
                    query_vector,
                    keywords,
                    citation,
                    unit_type="para",
                    limit=self.paragraph_limit,
                    per_leg=self.per_leg,
                )
            )
            candidates = tuple(
                self._select_candidates(
                    citation, query_vector, keywords, numbers, paragraph_hits
                )
            )
            verdict = self.verifier.verify(
                claim.text, citation, paper.title, candidates
            )
            error = None
        except Exception as exc:  # noqa: BLE001 - one failed citation must not abort the report
            verdict = Verdict(
                verdict="unknown",
                confidence="low",
                review_required=True,
                reason=f"核对失败：{type(exc).__name__}: {exc}",
                evidence=None,
            )
            error = f"{type(exc).__name__}: {exc}"

        return CitationCheck(
            citation=citation,
            paper=paper,
            verdict=verdict.verdict,
            confidence=verdict.confidence,
            review_required=verdict.review_required,
            reason=verdict.reason,
            evidence=verdict.evidence,
            keywords=keywords,
            number_status=(
                verdict.evidence.number_status if verdict.evidence is not None else "none"
            ),
            paragraph_hits=paragraph_hits,
            sentence_candidates=candidates,
            seconds=time.perf_counter() - start,
            error=error,
        )

    def _select_candidates(
        self,
        paper_key: str,
        query_vector: Sequence[float],
        keywords: tuple[str, ...],
        numbers: tuple[NumberMention, ...],
        paragraph_hits: Sequence[HybridHit],
    ) -> list[Evidence]:
        parent_ids = [hit.unit_id for hit in paragraph_hits[: self.paragraph_limit]]
        rows = self.store.fetch_children(paper_key, parent_ids)
        if not rows:
            rows = self.store.fetch_units(parent_ids)

        candidates: list[Evidence] = []
        for row in rows:
            if not row.text.strip():
                continue
            cosine = _cosine(query_vector, row.embedding)
            coverage = keyword_coverage(keywords, row.text)
            status = number_status(numbers, row.text)
            score = 0.60 * cosine + 0.35 * coverage
            if numbers:
                if status == "match":
                    score += 0.05
                elif status == "conflict":
                    score -= 0.10
                else:
                    score -= 0.05
            candidates.append(
                Evidence(
                    unit_id=row.unit_id,
                    paper_key=row.paper_key or paper_key,
                    page=row.page,
                    unit_type=row.unit_type,
                    parent_id=row.parent_id,
                    text=row.text,
                    score=score,
                    cosine=cosine,
                    keyword_coverage=coverage,
                    number_status=status,
                )
            )
        candidates.sort(key=lambda item: (-item.score, -item.cosine, item.unit_id))
        return candidates[: self.candidate_limit]


def _emit_progress(
    callback: ProgressCallback | None,
    *,
    stage: str,
    done: int,
    total: int,
    message: str,
    claim_id: str | None = None,
) -> None:
    if callback is None:
        return
    event: dict[str, Any] = {
        "stage": stage,
        "done": done,
        "total": total,
        "message": message,
    }
    if claim_id is not None:
        event["claim_id"] = claim_id
    callback(event)


def _worst_verdict(checks: Sequence[CitationCheck]) -> str:
    if not checks:
        return "unknown"
    return min(checks, key=lambda check: _VERDICT_ORDER[check.verdict]).verdict


def _cosine(left: Sequence[float] | None, right: Sequence[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
