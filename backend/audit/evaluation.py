from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..evidence.bibliography import KEY_PATTERN, PaperRef
from .claims import Claim
from .engine import AuditEngine
from .verdicts import VERDICTS


class LabelError(ValueError):
    pass


@dataclass(frozen=True)
class LabeledItem:
    item_id: str
    claim: str
    citation: str
    label: str
    evidence_pages: tuple[int, ...]
    evidence_units: tuple[str, ...]
    source: str
    notes: str


@dataclass(frozen=True)
class LabeledSet:
    name: str
    description: str
    items: tuple[LabeledItem, ...]


@dataclass(frozen=True)
class ItemResult:
    item_id: str
    claim: str
    citation: str
    expected: str
    predicted: str
    confidence: str
    review_required: bool
    expected_pages: tuple[int, ...]
    evidence_page: int | None
    evidence_unit_id: str | None
    evidence_hit: bool | None
    reason: str
    seconds: float
    error: str | None


@dataclass(frozen=True)
class EvaluationReport:
    run_id: str
    generated_at: str
    dataset: str
    description: str
    bib_path: str
    verifier: str
    embedding_model: str
    items: tuple[ItemResult, ...]
    metrics: dict[str, Any]


def load_labeled_set(path: Path) -> LabeledSet:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LabelError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LabelError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise LabelError(f"{path} must contain a JSON object")

    name = _text(payload.get("name"), "name")
    description = _text(payload.get("description", ""), "description", allow_empty=True)
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise LabelError(f"{path}: 'items' must be a non-empty array")

    seen: set[str] = set()
    items: list[LabeledItem] = []
    for index, raw in enumerate(raw_items, start=1):
        where = f"items[{index}]"
        if not isinstance(raw, dict):
            raise LabelError(f"{where} must be an object")
        item_id = _text(raw.get("id"), f"{where}.id")
        if item_id in seen:
            raise LabelError(f"duplicate item id: {item_id}")
        seen.add(item_id)

        claim = _text(raw.get("claim"), f"{where}.claim")
        citation = _text(raw.get("citation"), f"{where}.citation")
        if not KEY_PATTERN.match(citation):
            raise LabelError(f"{where}.citation is not a valid paper key: {citation!r}")
        label = _text(raw.get("label"), f"{where}.label").lower()
        if label not in VERDICTS:
            raise LabelError(f"{where}.label must be one of {', '.join(VERDICTS)}")

        pages = _pages(raw.get("evidence_pages", []), f"{where}.evidence_pages")
        units = _strings(raw.get("evidence_units", []), f"{where}.evidence_units")
        if units and not pages:
            raise LabelError(f"{where}: evidence_units require evidence_pages")
        items.append(
            LabeledItem(
                item_id=item_id,
                claim=claim,
                citation=citation,
                label=label,
                evidence_pages=pages,
                evidence_units=units,
                source=_text(raw.get("source", ""), f"{where}.source", allow_empty=True),
                notes=_text(raw.get("notes", ""), f"{where}.notes", allow_empty=True),
            )
        )
    return LabeledSet(name=name, description=description, items=tuple(items))


def evaluate(
    engine: AuditEngine,
    label_set: LabeledSet,
    refs: dict[str, PaperRef],
    bib_path: str,
) -> EvaluationReport:
    missing = sorted({item.citation for item in label_set.items} - refs.keys())
    if missing:
        raise LabelError("labels cite keys missing from bibliography: " + ", ".join(missing))

    claims = [
        Claim(
            claim_id=item.item_id,
            line_start=0,
            line_end=0,
            text=item.claim,
            citations=(item.citation,),
        )
        for item in label_set.items
    ]
    report = engine.audit(claims, refs, draft_path=f"labels:{label_set.name}", bib_path=bib_path)
    by_id = {claim.claim.claim_id: claim for claim in report.claims}

    results: list[ItemResult] = []
    for item in label_set.items:
        claim = by_id[item.item_id]
        if len(claim.checks) != 1:
            raise LabelError(f"{item.item_id}: expected exactly one citation check")
        check = claim.checks[0]
        evidence = check.evidence
        evidence_hit = None
        if item.evidence_pages:
            evidence_hit = evidence is not None and evidence.page in item.evidence_pages
        results.append(
            ItemResult(
                item_id=item.item_id,
                claim=item.claim,
                citation=item.citation,
                expected=item.label,
                predicted=check.verdict,
                confidence=check.confidence,
                review_required=check.review_required,
                expected_pages=item.evidence_pages,
                evidence_page=evidence.page if evidence else None,
                evidence_unit_id=evidence.unit_id if evidence else None,
                evidence_hit=evidence_hit,
                reason=check.reason,
                seconds=round(check.seconds, 3),
                error=check.error,
            )
        )

    return EvaluationReport(
        run_id=report.run_id,
        generated_at=report.generated_at,
        dataset=label_set.name,
        description=label_set.description,
        bib_path=bib_path,
        verifier=report.verifier,
        embedding_model=report.embedding_model,
        items=tuple(results),
        metrics=compute_metrics(results),
    )


def compute_metrics(items: Sequence[ItemResult]) -> dict[str, Any]:
    total = len(items)
    labels = dict.fromkeys(VERDICTS, 0)
    predictions = dict.fromkeys(VERDICTS, 0)
    confusion = {expected: dict.fromkeys(VERDICTS, 0) for expected in VERDICTS}
    for item in items:
        labels[item.expected] += 1
        predictions[item.predicted] += 1
        confusion[item.expected][item.predicted] += 1

    true_negative = labels["unsupported"]
    true_positive = confusion["unsupported"]["unsupported"]
    false_positive = predictions["unsupported"] - true_positive
    false_negative = true_negative - true_positive
    unsupported_auto_pass = confusion["unsupported"]["supported"]
    unsupported_handled = true_negative - unsupported_auto_pass

    positive = labels["supported"]
    supported_review = sum(
        1
        for item in items
        if item.expected == "supported" and item.predicted in {"partial", "unknown"}
    )
    supported_auto = confusion["supported"]["supported"]
    review = sum(1 for item in items if item.predicted in {"partial", "unknown"})
    with_evidence = sum(1 for item in items if item.evidence_page is not None)
    page_labeled = [item for item in items if item.expected_pages]
    page_hits = sum(1 for item in page_labeled if item.evidence_hit)
    errors = sum(1 for item in items if item.error)
    seconds = sum(item.seconds for item in items)

    return {
        "total": total,
        "labels": labels,
        "predictions": predictions,
        "confusion": confusion,
        "strict_accuracy": _ratio(sum(1 for item in items if item.expected == item.predicted), total),
        "unsupported_recall": _ratio(true_positive, true_negative),
        "unsupported_precision": _ratio(true_positive, true_positive + false_positive),
        "unsupported_f1": _f1(true_positive, false_positive, false_negative),
        "unsupported_missed": false_negative,
        "unsupported_auto_pass": unsupported_auto_pass,
        "unsupported_handled_rate": _ratio(unsupported_handled, true_negative),
        "review_rate": _ratio(review, total),
        "supported_review_rate": _ratio(supported_review, positive),
        "supported_auto_rate": _ratio(supported_auto, positive),
        "evidence_coverage": _ratio(with_evidence, total),
        "evidence_page_labeled": len(page_labeled),
        "evidence_page_hit_rate": _ratio(page_hits, len(page_labeled)),
        "mean_seconds": _ratio(seconds, total),
        "errors": errors,
    }


def evaluation_to_dict(report: EvaluationReport) -> dict[str, Any]:
    return {
        "run_id": report.run_id,
        "generated_at": report.generated_at,
        "dataset": report.dataset,
        "description": report.description,
        "bib": report.bib_path,
        "verifier": report.verifier,
        "embedding_model": report.embedding_model,
        "baseline_cannot_emit_supported": report.verifier.startswith("none"),
        "metrics": report.metrics,
        "items": [
            {
                **asdict(item),
                "expected_pages": list(item.expected_pages),
            }
            for item in report.items
        ],
    }


def evaluation_to_markdown(report: EvaluationReport) -> str:
    metrics = report.metrics
    lines = [
        "# 引用核对评测报告",
        "",
        f"- 数据集：`{report.dataset}`（{len(report.items)} 条）",
        f"- 数据集说明：{report.description or '—'}",
        f"- 论文库：`{report.bib_path}`",
        f"- 生成时间：{report.generated_at}",
        f"- 判定器：`{report.verifier}`",
        f"- 向量模型：`{report.embedding_model}`",
        "",
        "## 指标口径",
        "",
        "- **不支持召回率**：人工标为无支持的条目中，被判为 `unsupported` 的比例；",
        "- **不支持精确率**：所有 `unsupported` 判定中，人工标注确实无支持的比例；",
        "- **复核率**：判为 `partial` 或 `unknown`、仍需人工确认的比例；",
        "- **无支持自动放行**：人工标为无支持、却被判为 `supported` 的条数，是最危险的错误；",
        "- **无支持处理率**：人工标为无支持的条目中，被判 `unsupported` 或需复核的比例；",
        "- **证据页命中率**：有证据页标注的条目中，系统证据落在标注页内的比例（无证据按未命中）；",
        "- **严格准确率**：四档判定与人工标注完全一致的比例。",
        "",
        "## 汇总",
        "",
        "| 指标 | 值 |",
        "| --- | ---: |",
        f"| 条目 | {metrics['total']} |",
        (
            f"| 标注 supported / unsupported | {metrics['labels']['supported']} / "
            f"{metrics['labels']['unsupported']} |"
        ),
        (
            "| 判为 supported / partial / unsupported / unknown | "
            f"{metrics['predictions']['supported']} / {metrics['predictions']['partial']} / "
            f"{metrics['predictions']['unsupported']} / {metrics['predictions']['unknown']} |"
        ),
        f"| 严格准确率 | {_pct(metrics['strict_accuracy'])} |",
        f"| 不支持召回率 | {_pct(metrics['unsupported_recall'])} |",
        f"| 不支持精确率 | {_pct(metrics['unsupported_precision'])} |",
        f"| 不支持 F1 | {_pct(metrics['unsupported_f1'])} |",
        f"| 漏判无支持 | {metrics['unsupported_missed']} |",
        f"| 无支持自动放行 | {metrics['unsupported_auto_pass']} |",
        f"| 无支持处理率 | {_pct(metrics['unsupported_handled_rate'])} |",
        f"| 复核率 | {_pct(metrics['review_rate'])} |",
        f"| supported 条目仍需复核 | {_pct(metrics['supported_review_rate'])} |",
        f"| supported 自动通过 | {_pct(metrics['supported_auto_rate'])} |",
        f"| 有证据条目 | {_pct(metrics['evidence_coverage'])} |",
        (
            f"| 证据页命中率 | {_pct(metrics['evidence_page_hit_rate'])}"
            f"（{metrics['evidence_page_labeled']} 条有页标注） |"
        ),
        f"| 平均单条耗时 | {metrics['mean_seconds']:.3f}s |",
        f"| 核对错误 | {metrics['errors']} |",
        "",
    ]
    if report.verifier.startswith("none"):
        lines.extend(
            [
                (
                    "> `verifier=none` 为无 key 基线：按设计不出具 `supported`，"
                    "因此 supported 自动通过率与严格准确率不能当作模型能力上限；"
                    "本表的主要结论应看不支持召回与复核工作量。"
                ),
                "",
            ]
        )

    lines.extend(
        [
            "## 混淆矩阵",
            "",
            "| 标注 \\ 判定 | supported | partial | unsupported | unknown |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for expected in VERDICTS:
        row = metrics["confusion"][expected]
        lines.append(
            f"| {expected} | {row['supported']} | {row['partial']} | "
            f"{row['unsupported']} | {row['unknown']} |"
        )
    lines.extend(
        [
            "",
            "## 逐条结果",
            "",
            "| id | 标注 | 判定 | 证据页 | 页命中 | 复核 | 置信度 |",
            "| --- | --- | --- | ---: | --- | --- | --- |",
        ]
    )
    for item in report.items:
        hit = "—" if item.evidence_hit is None else ("是" if item.evidence_hit else "否")
        lines.append(
            f"| {item.item_id} | {item.expected} | {item.predicted} | "
            f"{item.evidence_page if item.evidence_page is not None else '—'} | {hit} | "
            f"{'是' if item.review_required else '否'} | {item.confidence} |"
        )
    lines.extend(["", "### 判定理由", ""])
    for item in report.items:
        suffix = f"；错误：{item.error}" if item.error else ""
        lines.append(
            f"- **{item.item_id}** `{item.expected} → {item.predicted}`：{item.reason}{suffix}"
        )
    return "\n".join(lines).rstrip() + "\n"


def write_evaluation(report: EvaluationReport, out_dir: Path) -> dict[str, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", report.dataset)[:40] or "eval"
    paths = {
        "markdown": directory / f"{stem}.md",
        "json": directory / f"{stem}.json",
    }
    _write(paths["markdown"], evaluation_to_markdown(report), encoding="utf-8")
    _write(
        paths["json"],
        json.dumps(evaluation_to_dict(report), ensure_ascii=False, indent=2) + "\n",
    )
    return paths


def _write(path: Path, content: str, encoding: str = "utf-8") -> None:
    with path.open("w", encoding=encoding, newline="\n") as handle:
        handle.write(content)


def _text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise LabelError(f"{field} must be a string")
    text = value.strip()
    if not text and not allow_empty:
        raise LabelError(f"{field} must not be empty")
    return text


def _pages(value: Any, field: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise LabelError(f"{field} must be an array")
    pages: list[int] = []
    for page in value:
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise LabelError(f"{field} must contain positive integers")
        pages.append(page)
    if len(set(pages)) != len(pages):
        raise LabelError(f"{field} contains duplicate pages")
    return tuple(pages)


def _strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise LabelError(f"{field} must be an array of strings")
    return tuple(item.strip() for item in value if item.strip())


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _f1(true_positive: int, false_positive: int, false_negative: int) -> float | None:
    denominator = 2 * true_positive + false_positive + false_negative
    if denominator == 0:
        return None
    return round(2 * true_positive / denominator, 4)


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1%}"
