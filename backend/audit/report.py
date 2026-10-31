from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .engine import AuditReport, CitationCheck, ClaimCheck

_VERDICT_LABELS = {
    "supported": "支持",
    "partial": "部分支持",
    "unsupported": "不支持",
    "unknown": "无法判断",
}


def report_to_dict(report: AuditReport) -> dict[str, Any]:
    return {
        "run_id": report.run_id,
        "generated_at": report.generated_at,
        "draft": report.draft_path,
        "bib": report.bib_path,
        "verifier": report.verifier,
        "embedding_model": report.embedding_model,
        "unit_mode": report.unit_mode,
        "summary": {
            "claims": len(report.claims),
            "citations": report.citation_count,
            "claim_verdicts": report.claim_verdicts,
            "citation_verdicts": report.citation_verdicts,
            "review_required": report.review_count,
            "errors": report.error_count,
        },
        "warnings": list(report.warnings),
        "claims": [_claim_to_dict(claim) for claim in report.claims],
    }


def report_to_markdown(report: AuditReport) -> str:
    lines = [
        "# 引用核对报告",
        "",
        f"- 草稿：`{report.draft_path}`",
        f"- 论文库：`{report.bib_path}`",
        f"- 生成时间：{report.generated_at}",
        f"- 判定器：`{report.verifier}`",
        f"- 向量模型：`{report.embedding_model}`",
        f"- 证据单元：`{report.unit_mode}`",
        "",
        "## 结论口径",
        "",
        "- **支持**：原文直接蕴含主张；**部分支持**：只支持弱化版本或部分限定；",
        "- **不支持**：原文矛盾，或被引论文内找不到支持；**无法判断**：检索失败或证据不足。",
        "- `verifier=none` 为无 key 基线：不会出具“支持”，`部分支持` 表示高度相关但需人工确认。",
        "",
        "## 汇总",
        "",
        "| 范围 | 支持 | 部分支持 | 不支持 | 无法判断 |",
        "| --- | ---: | ---: | ---: | ---: |",
        _counts_row("主张", report.claim_verdicts),
        _counts_row("引用", report.citation_verdicts),
        "",
        (
            f"共 {len(report.claims)} 条主张 / {report.citation_count} 条引用；"
            f"需人工复核 {report.review_count} 条；错误 {report.error_count} 条。"
        ),
        "",
    ]
    if report.warnings:
        lines.extend(["## 提示", ""])
        lines.extend(f"- {warning}" for warning in report.warnings)
        lines.append("")

    for claim in report.claims:
        lines.extend(_claim_markdown(claim))

    return "\n".join(lines).rstrip() + "\n"


def report_to_csv(report: AuditReport) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "claim_id",
            "line_start",
            "line_end",
            "claim",
            "citation",
            "paper_title",
            "verdict",
            "confidence",
            "review_required",
            "page",
            "evidence_id",
            "evidence_type",
            "quote",
            "score",
            "cosine",
            "keyword_coverage",
            "number_status",
            "reason",
            "error",
        ]
    )
    for claim in report.claims:
        for check in claim.checks:
            evidence = check.evidence
            writer.writerow(
                [
                    claim.claim.claim_id,
                    claim.claim.line_start,
                    claim.claim.line_end,
                    claim.claim.text,
                    check.citation,
                    check.paper.title,
                    check.verdict,
                    check.confidence,
                    "yes" if check.review_required else "no",
                    evidence.page if evidence else "",
                    evidence.unit_id if evidence else "",
                    evidence.unit_type if evidence else "",
                    evidence.text if evidence else "",
                    f"{evidence.score:.4f}" if evidence else "",
                    f"{evidence.cosine:.4f}" if evidence else "",
                    f"{evidence.keyword_coverage:.4f}" if evidence else "",
                    check.number_status,
                    check.reason,
                    check.error or "",
                ]
            )
    return buffer.getvalue()


def write_reports(report: AuditReport, out_dir: Path) -> dict[str, Path]:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(report.draft_path).stem)[:40] or "draft"
    directory = Path(out_dir) / f"{report.run_id}-{stem}"
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "markdown": directory / "report.md",
        "csv": directory / "report.csv",
        "json": directory / "report.json",
    }
    _write(paths["markdown"], report_to_markdown(report), encoding="utf-8")
    _write(paths["csv"], report_to_csv(report), encoding="utf-8-sig")
    _write(paths["json"], json.dumps(report_to_dict(report), ensure_ascii=False, indent=2) + "\n")
    return paths


def _write(path: Path, content: str, encoding: str = "utf-8") -> None:
    with path.open("w", encoding=encoding, newline="\n") as handle:
        handle.write(content)


def _counts_row(label: str, counts: dict[str, int]) -> str:
    return (
        f"| {label} | {counts.get('supported', 0)} | {counts.get('partial', 0)} | "
        f"{counts.get('unsupported', 0)} | {counts.get('unknown', 0)} |"
    )


def _claim_markdown(claim: ClaimCheck) -> list[str]:
    source = claim.claim
    lines = [
        f"## {source.claim_id} · 第 {source.line_start}–{source.line_end} 行",
        "",
        f"> {source.text}",
        "",
        (
            f"主张结论：**{_VERDICT_LABELS.get(claim.verdict, claim.verdict)}**"
            f"（{claim.verdict}，{claim.seconds:.2f}s）"
        ),
        "",
    ]
    for check in claim.checks:
        lines.extend(_check_markdown(check))
    return lines


def _check_markdown(check: CitationCheck) -> list[str]:
    title = check.paper.title or check.paper.paper_key
    lines = [
        f"### @{check.citation} — {title}",
        "",
        (
            f"- 结论：**{_VERDICT_LABELS.get(check.verdict, check.verdict)}**"
            f"（{check.verdict}；置信度 {check.confidence}；"
            f"{'需人工复核' if check.review_required else '无需复核'}）"
        ),
        f"- 理由：{check.reason}",
        (
            f"- 检索关键词：`{' '.join(check.keywords) or '(none)'}`；"
            f"数字状态：`{check.number_status}`；耗时 {check.seconds:.2f}s"
        ),
    ]
    if check.error:
        lines.append(f"- 错误：`{check.error}`")
    evidence = check.evidence
    if evidence is None:
        lines.extend(["", "证据：无", ""])
    else:
        lines.extend(
            [
                "",
                (
                    f"证据：p{evidence.page} · `{evidence.unit_id}` · {evidence.unit_type} · "
                    f"score={evidence.score:.3f} · cos={evidence.cosine:.3f} · "
                    f"覆盖={evidence.keyword_coverage:.0%}"
                ),
                "",
                _blockquote(evidence.text),
                "",
            ]
        )

    if check.paragraph_hits:
        lines.extend(
            [
                "段落检索（先取段落）：",
                "",
                "| # | 段落 id | 页 | RRF | 全文排名 | 向量排名 |",
                "| ---: | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for rank, hit in enumerate(check.paragraph_hits, start=1):
            lines.append(
                f"| {rank} | `{hit.unit_id}` | {hit.page} | {hit.rrf_score:.4f} | "
                f"{_rank(hit.fulltext_rank)} | {_rank(hit.vector_rank)} |"
            )
        lines.append("")

    if check.sentence_candidates:
        lines.extend(
            [
                "句内候选（再选证据）：",
                "",
                "| # | 句子 id | 页 | score | cos | 覆盖 | 数字 |",
                "| ---: | --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for rank, candidate in enumerate(check.sentence_candidates[:5], start=1):
            lines.append(
                f"| {rank} | `{candidate.unit_id}` | {candidate.page} | "
                f"{candidate.score:.3f} | {candidate.cosine:.3f} | "
                f"{candidate.keyword_coverage:.0%} | {candidate.number_status} |"
            )
        lines.append("")
    return lines


def _blockquote(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines() if line.strip())


def _rank(rank: int | None) -> str:
    return str(rank) if rank is not None else "-"


def _claim_to_dict(claim: ClaimCheck) -> dict[str, Any]:
    return {
        "claim_id": claim.claim.claim_id,
        "line_start": claim.claim.line_start,
        "line_end": claim.claim.line_end,
        "text": claim.claim.text,
        "citations": list(claim.claim.citations),
        "verdict": claim.verdict,
        "seconds": round(claim.seconds, 3),
        "checks": [_check_to_dict(check) for check in claim.checks],
    }


def _check_to_dict(check: CitationCheck) -> dict[str, Any]:
    return {
        "citation": check.citation,
        "paper": asdict(check.paper),
        "verdict": check.verdict,
        "confidence": check.confidence,
        "review_required": check.review_required,
        "reason": check.reason,
        "keywords": list(check.keywords),
        "number_status": check.number_status,
        "seconds": round(check.seconds, 3),
        "error": check.error,
        "evidence": asdict(check.evidence) if check.evidence else None,
        "paragraph_hits": [asdict(hit) for hit in check.paragraph_hits],
        "sentence_candidates": [asdict(candidate) for candidate in check.sentence_candidates],
    }
