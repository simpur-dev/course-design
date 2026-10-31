import pymupdf
import pytest

from backend.memory.client import HandoffView, MemoryEntry


class FakePowerContext:
    def __init__(self) -> None:
        self.scopes: dict[str, dict] = {}
        self.entries: dict[str, list[MemoryEntry]] = {}
        self.handoffs: dict[str, list[dict]] = {}
        self.closed = False
        self.last_remember: dict | None = None

    def ensure_scope(self, title: str, summary: str) -> dict:
        if title not in self.scopes:
            scope_id = f"scp_{len(self.scopes) + 1}"
            self.scopes[title] = {
                "scope_id": scope_id,
                "title": title,
                "summary": summary,
                "parent_scope_id": None,
                "context_references": [],
                "external_references": [],
                "version": 1,
            }
        return self.scopes[title]

    def list_scopes(self, prefix: str = "cd:") -> list[dict]:
        return [scope for title, scope in self.scopes.items() if title.startswith(prefix)]

    def remember(
        self,
        scope_id: str,
        kind: str,
        text: str,
        reason: str | None = None,
    ) -> list[MemoryEntry]:
        self.last_remember = {"scope_id": scope_id, "kind": kind, "text": text, "reason": reason}
        entries = self.entries.setdefault(scope_id, [])
        entry = MemoryEntry(
            artifact_id=f"art_{len(entries) + 1}",
            revision=1,
            kind=kind,
            text=text,
            state="active",
            state_version=0,
        )
        entries.append(entry)
        return [entry]

    def list_entries(
        self, scope_id: str, limit: int | None = 200
    ) -> list[MemoryEntry]:
        entries = self.entries.get(scope_id, [])
        return entries if limit is None else entries[:limit]

    def search(self, scope_id: str, query: str, limit: int = 10) -> list[dict]:
        hits = []
        for entry in self.entries.get(scope_id, []):
            if query in entry.text:
                hits.append(
                    {
                        "memory": {
                            "artifact": {
                                "family": "atomic-memory",
                                "artifact_id": entry.artifact_id,
                                "revision": entry.revision,
                            },
                            "kind": entry.kind,
                            "text": entry.text,
                            "state": entry.state,
                            "state_version": entry.state_version,
                            "merged_into_id": None,
                        },
                        "score": 1.0,
                        "matched_by": ["text"],
                    }
                )
        return hits[:limit]

    def commit_handoff(self, scope_id: str, draft: dict) -> tuple[dict, HandoffView]:
        handoffs = self.handoffs.setdefault(scope_id, [])
        if not handoffs or handoffs[-1] != draft:
            handoffs.append(draft)
        revision = len(handoffs)
        reference = {"family": "handoff", "artifact_id": "handoff", "revision": revision}
        checks = tuple(
            {
                "claim": "state",
                "state_index": index,
                "status": "available",
                "unavailable_evidence": [],
            }
            for index in range(len(draft["state"]))
        ) + (
            {
                "claim": "next_action",
                "state_index": None,
                "status": "available",
                "unavailable_evidence": [],
            },
        )
        view = HandoffView(
            status="resolved",
            trust="untrusted_history",
            content=draft,
            evidence_checks=checks,
            selected_revision=reference,
            current_revision=reference,
        )
        return (
            {
                "reference": reference,
                "content": draft,
                "source_refs": [],
                "artifact_refs": [],
            },
            view,
        )

    def continue_handoff(self, scope_id: str, selection: str = "latest") -> HandoffView:
        handoffs = self.handoffs.get(scope_id, [])
        if not handoffs:
            return HandoffView("empty", "untrusted_history", None, (), None, None)
        revision = len(handoffs)
        reference = {"family": "handoff", "artifact_id": "handoff", "revision": revision}
        return HandoffView(
            status="resolved",
            trust="untrusted_history",
            content=handoffs[-1],
            evidence_checks=(),
            selected_revision=reference,
            current_revision=reference,
        )

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_powercontext() -> FakePowerContext:
    return FakePowerContext()


@pytest.fixture
def make_pdf():
    def _make(path, pages: list[str]) -> None:
        path.unlink(missing_ok=True)
        document = pymupdf.open()
        try:
            for text in pages:
                page = document.new_page()
                if text:
                    page.insert_textbox(pymupdf.Rect(72, 72, 523, 770), text, fontsize=11)
            document.save(path)
        finally:
            document.close()

    return _make
