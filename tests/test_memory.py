from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from backend import memory as memory_module
from backend.audit import AuditReport, CitationCheck, ClaimCheck
from backend.audit.claims import Claim
from backend.audit.verdicts import Evidence
from backend.core.config import Settings
from backend.evidence.store import PaperRecord
from backend.memory import (
    build_handoff_draft,
    claim_decision_text,
    is_pending,
    project_id_for_path,
    run_summary_text,
    scope_title,
    sync_report_memory,
    sync_with_client,
    validate_project_id,
)
from backend.memory.client import PowerContextError

PAPER = PaperRecord(
    paper_key="bert",
    title="BERT",
    authors="Devlin",
    year=2019,
    source_url="",
    file_name="bert.pdf",
    file_sha256="sha",
    page_count=10,
    para_count=20,
    sent_count=30,
    unit_mode="sent",
    ingested_at="2026-01-01T00:00:00+00:00",
)
EVIDENCE = Evidence(
    unit_id="bert:p1:s1",
    paper_key="bert",
    page=1,
    unit_type="sent",
    parent_id="bert:p1:para1",
    text="BERT uses masked language modeling.",
    score=0.8,
    cosine=0.8,
    keyword_coverage=0.7,
    number_status="none",
)


def _check(verdict: str, review: bool, reason: str = "evidence needs confirmation") -> CitationCheck:
    return CitationCheck(
        citation="bert",
        paper=PAPER,
        verdict=verdict,
        confidence="medium",
        review_required=review,
        reason=reason,
        evidence=EVIDENCE,
        keywords=("bert",),
        number_status="none",
        paragraph_hits=(),
        sentence_candidates=(),
        seconds=0.01,
    )


def _report(claims: int = 4, run_id: str = "20261026T090000000000Z") -> AuditReport:
    checks = []
    for index in range(1, claims + 1):
        verdict = "partial" if index % 2 else "unknown"
        checks.append(
            ClaimCheck(
                claim=Claim(
                    claim_id=f"claim-{index:02d}",
                    line_start=index,
                    line_end=index,
                    text=f"claim text {index}",
                    citations=("bert",),
                ),
                checks=(_check(verdict, True, f"reason for claim {index}"),),
                verdict=verdict,
                seconds=0.01,
            )
        )
    return AuditReport(
        run_id=run_id,
        generated_at="2026-10-26T09:00:00+00:00",
        draft_path="data/samples/draft.md",
        bib_path="data/samples/bib.json",
        verifier="none/baseline",
        embedding_model="local",
        claims=tuple(checks),
        warnings=(),
    )


def test_project_ids_are_path_scoped(tmp_path: Path) -> None:
    data = tmp_path / "data"
    bib = data / "samples" / "bib.json"
    assert project_id_for_path(data, bib) == "samples/bib"
    assert project_id_for_path(data, tmp_path / "outside.json") == "outside"
    assert scope_title("samples/bib") == "cd:samples/bib"
    with pytest.raises(ValueError):
        validate_project_id("../escape")
    with pytest.raises(ValueError):
        validate_project_id("bad project")


def test_memory_texts_and_pending_rule() -> None:
    report = _report()
    first = report.claims[0]
    assert claim_decision_text(report, first).startswith(report.run_id)
    assert "claim-01" in claim_decision_text(report, first)
    assert "partial" in claim_decision_text(report, first)
    assert "主张 4 条" in run_summary_text(report)
    assert "需复核 4 条" in run_summary_text(report)
    assert is_pending(report.claims[0]) is True
    non_pending = ClaimCheck(
        claim=report.claims[1].claim,
        checks=(_check("unsupported", False, "no support"),),
        verdict="unsupported",
        seconds=0.01,
    )
    assert is_pending(non_pending) is False


def test_handoff_draft_cites_matching_claims() -> None:
    report = _report()
    refs = {
        f"claim-{index:02d}": {
            "kind": "artifact",
            "artifact_ref": {
                "family": "atomic-memory",
                "artifact_id": f"art_decision_{index}",
                "revision": 1,
            },
        }
        for index in range(1, 5)
    }
    next_refs = {
        f"claim-{index:02d}": {
            "kind": "artifact",
            "artifact_ref": {
                "family": "atomic-memory",
                "artifact_id": f"art_next_{index}",
                "revision": 1,
            },
        }
        for index in range(1, 5)
    }
    criterion = {
        "kind": "artifact",
        "artifact_ref": {
            "family": "atomic-memory",
            "artifact_id": "art_criterion",
            "revision": 1,
        },
    }
    draft = build_handoff_draft(
        report,
        "samples/bib",
        summary_ref=refs["claim-01"],
        criterion_ref=criterion,
        decision_refs=list(refs.values()),
        next_refs=list(next_refs.values()),
        decision_by_claim={key: [value] for key, value in refs.items()},
        next_by_claim={key: [value] for key, value in next_refs.items()},
        pending=[claim for claim in report.claims if is_pending(claim)],
    )
    assert draft["disposition"] == "continuable"
    assert len(draft["state"]) == 5
    claim_statement = draft["state"][2]
    assert "claim-01" in claim_statement["text"]
    assert claim_statement["citations"][0]["artifact_ref"]["artifact_id"] == "art_decision_1"
    assert draft["next_action"]["citations"][0]["artifact_ref"]["artifact_id"].startswith(
        "art_next_"
    )
    assert draft["omissions"][0] == {
        "text": "另有 1 条待复核未逐条列入交接。",
        "citation": next_refs["claim-01"],
    }


def test_handoff_complete_without_pending() -> None:
    report = _report(claims=2)
    report = AuditReport(
        **{
            **report.__dict__,
            "claims": tuple(
                ClaimCheck(
                    claim=claim.claim,
                    checks=(_check("unsupported", False, "no support"),),
                    verdict="unsupported",
                    seconds=0.01,
                )
                for claim in report.claims
            ),
        }
    )
    criterion = {
        "kind": "artifact",
        "artifact_ref": {
            "family": "atomic-memory",
            "artifact_id": "art_criterion",
            "revision": 1,
        },
    }
    draft = build_handoff_draft(
        report,
        "samples/bib",
        summary_ref=None,
        criterion_ref=criterion,
        decision_refs=[],
        next_refs=[],
        decision_by_claim={},
        next_by_claim={},
        pending=[],
    )
    assert draft["disposition"] == "complete"
    assert "没有待复核项" in draft["next_action"]["text"]
    assert draft["omissions"] == []
    assert all(statement["citations"] for statement in draft["state"])


def test_sync_is_idempotent_and_dedupes_handoff(fake_powercontext) -> None:
    report = _report()
    first = sync_with_client(fake_powercontext, "samples/bib", report)
    assert first.ok is True
    assert first.written == 13
    assert first.skipped == 0
    assert first.handoff is not None
    assert first.handoff["revision"] == 1
    assert first.handoff["status"] == "resolved"
    assert first.handoff["trust"] == "untrusted_history"
    assert first.handoff["content"]["disposition"] == "continuable"

    second = sync_with_client(fake_powercontext, "samples/bib", report)
    assert second.written == 0
    assert second.skipped == 13
    assert second.handoff is not None
    assert second.handoff["revision"] == 1

    stored = fake_powercontext.list_entries(first.scope_id or "", limit=100)
    assert len(stored) == 13
    assert sum(1 for entry in stored if entry.kind == "criterion") == 3
    assert sum(1 for entry in stored if entry.kind == "decision") == 5
    assert sum(1 for entry in stored if entry.kind == "next_step") == 4


def test_new_run_appends_decisions_and_bumps_handoff(fake_powercontext) -> None:
    report = _report()
    first = sync_with_client(fake_powercontext, "samples/bib", report)
    assert first.handoff is not None

    rerun = sync_with_client(
        fake_powercontext,
        "samples/bib",
        replace(report, run_id="20261026T091600000000Z"),
    )
    assert rerun.written == 9
    assert rerun.skipped == 4
    assert rerun.handoff is not None
    assert rerun.handoff["revision"] == 2

    stored = fake_powercontext.list_entries(first.scope_id or "", limit=100)
    assert len(stored) == 22


def test_sync_disabled_and_unavailable(tmp_path: Path, monkeypatch) -> None:
    disabled = Settings(_env_file=None, data_dir=tmp_path / "data", memory_enabled=False)
    result = sync_report_memory(disabled, _report(), tmp_path / "data" / "samples" / "bib.json")
    assert result.ok is False
    assert result.enabled is False
    assert "未启用" in (result.error or "")

    class BrokenClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def ensure_scope(self, title: str, summary: str) -> dict:
            raise PowerContextError("connection refused", "docker compose up -d powercontext")

        def close(self) -> None:
            pass

    monkeypatch.setattr(memory_module.sync, "PowerContextClient", BrokenClient)
    enabled = Settings(_env_file=None, data_dir=tmp_path / "data", memory_enabled=True)
    failed = sync_report_memory(enabled, _report(), tmp_path / "data" / "samples" / "bib.json")
    assert failed.ok is False
    assert failed.project == "samples/bib"
    assert "refused" in (failed.error or "")
    assert failed.hint == "docker compose up -d powercontext"
    assert failed.to_dict()["handoff"] is None
