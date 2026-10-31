from __future__ import annotations

import os
import uuid
from dataclasses import replace

import pytest

from yinju.audit import AuditReport, CitationCheck, ClaimCheck
from yinju.claims import Claim
from yinju.memory import sync_with_client
from yinju.powercontext import PowerContextClient
from yinju.store import PaperRecord
from yinju.verdicts import Evidence

BASE_URL = os.environ.get("YINJU_TEST_POWERCONTEXT_URL", "")
pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="set YINJU_TEST_POWERCONTEXT_URL to a disposable PowerContext server",
)

PAPER = PaperRecord("bert", "BERT", "Devlin", 2019, "", "b.pdf", "sha", 1, 1, 1, "sent", "now")
EVIDENCE = Evidence("bert:p1:s1", "bert", 1, "sent", "bert:p1:para1", "text", 0.8, 0.8, 0.7, "none")


def _report() -> AuditReport:
    claim = ClaimCheck(
        claim=Claim("claim-01", 1, 1, "BERT uses masked language modeling.", ("bert",)),
        checks=(
            CitationCheck(
                "bert",
                PAPER,
                "partial",
                "medium",
                True,
                "evidence needs confirmation",
                EVIDENCE,
                ("bert",),
                "none",
                (),
                (),
                0.01,
            ),
        ),
        verdict="partial",
        seconds=0.01,
    )
    return AuditReport(
        run_id="20261026T091500000000Z",
        generated_at="2026-10-26T09:15:00+00:00",
        draft_path="data/samples/draft.md",
        bib_path="data/samples/bib.json",
        verifier="none/baseline",
        embedding_model="local",
        claims=(claim,),
        warnings=(),
    )


def test_powercontext_memory_and_handoff_roundtrip() -> None:
    project = f"pytest-{uuid.uuid4().hex[:10]}"
    client = PowerContextClient(BASE_URL, timeout=10.0)
    try:
        first = sync_with_client(client, project, _report())
        assert first.ok is True
        assert first.written == 7
        assert first.handoff is not None
        assert first.handoff["revision"] == 1
        assert first.handoff["trust"] == "untrusted_history"
        assert first.handoff["status"] == "resolved"
        assert first.handoff["content"]["disposition"] == "continuable"
        assert all(
            check["status"] == "available" for check in first.handoff["evidence_checks"]
        )

        second = sync_with_client(client, project, _report())
        assert second.written == 0
        assert second.skipped == 7
        assert second.handoff is not None
        # PowerContext treats an identical handoff commit as idempotent.
        assert second.handoff["revision"] == 1

        entries = client.list_entries(second.scope_id or "", limit=100)
        assert len(entries) == 7
        hits = client.search(second.scope_id or "", "confirmation", limit=5)
        assert hits
        view = client.continue_handoff(second.scope_id or "")
        assert view.status == "resolved"
        assert view.current_revision is not None
        assert view.current_revision["revision"] == 1

        third = sync_with_client(
            client,
            project,
            replace(_report(), run_id="20261026T091600000000Z"),
        )
        assert third.written == 3
        assert third.skipped == 4
        assert third.handoff is not None
        assert third.handoff["revision"] == 2
        assert len(client.list_entries(third.scope_id or "", limit=100)) == 10
        latest = client.continue_handoff(third.scope_id or "")
        assert latest.current_revision is not None
        assert latest.current_revision["revision"] == 2
    finally:
        client.close()
