from __future__ import annotations

import json

import httpx
import pytest

from yinju.powercontext import MemoryEntry, PowerContextClient, PowerContextError


def _entry_payload(entry: MemoryEntry) -> dict:
    return {
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
    }


def _client(fake, seen: list[httpx.Request]) -> PowerContextClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        body = json.loads(request.content) if request.content else {}

        if path == "/v1/scopes" and request.method == "POST":
            return httpx.Response(201, json=fake.ensure_scope(body["title"], body["summary"]))
        if path == "/v1/scopes":
            return httpx.Response(
                200, json={"items": fake.list_scopes(), "next_cursor": None}
            )
        if path == "/v1/memory/remember":
            records = fake.remember(
                body["scope_id"], body["kind"], body["text"], body.get("reason")
            )
            return httpx.Response(
                200, json={"changed": True, "records": [_entry_payload(item) for item in records]}
            )
        if path == "/v1/memory/entries/list":
            entries = fake.list_entries(body["scope_id"], body.get("limit", 50))
            return httpx.Response(
                200,
                json={"entries": [_entry_payload(item) for item in entries], "next_cursor": None},
            )
        if path == "/v1/memory/search":
            return httpx.Response(
                200,
                json={"mode": "text", "hits": fake.search(body["scope_id"], body["query"])},
            )
        if path == "/v1/handoff/finalize":
            draft = body["draft"]
            return httpx.Response(
                200,
                json={
                    "schema": "powercontext.prepared-handoff.v1",
                    "scope_id": body["scope_id"],
                    "base": None,
                    "content": draft,
                    "generation": None,
                },
            )
        if path == "/v1/handoff/commit":
            committed, _ = fake.commit_handoff(body["scope_id"], body["handoff"]["content"])
            return httpx.Response(200, json=committed)
        if path == "/v1/handoff/continue":
            view = fake.continue_handoff(body["scope_id"], body.get("selection", "latest"))
            return httpx.Response(200, json=view.to_dict())
        return httpx.Response(404, json={"error": {"message": "not found", "code": "not_found"}})

    transport = httpx.MockTransport(handler)
    return PowerContextClient(
        "http://pc.test",
        token="test-token",
        client=httpx.Client(transport=transport, timeout=1.0),
    )


def test_scope_remember_list_and_search(fake_powercontext) -> None:
    seen: list[httpx.Request] = []
    client = _client(fake_powercontext, seen)

    scope = client.ensure_scope("yj:samples/bib", "引据项目 samples/bib")
    again = client.ensure_scope("yj:samples/bib", "引据项目 samples/bib")
    assert scope["scope_id"] == again["scope_id"] == "scp_1"

    records = client.remember(scope["scope_id"], "criterion", "证据必须给出页码", reason="test")
    assert records[0].kind == "criterion"
    assert records[0].citation["artifact_ref"]["family"] == "atomic-memory"

    entries = client.list_entries(scope["scope_id"], limit=20)
    assert [entry.text for entry in entries] == ["证据必须给出页码"]

    hits = client.search(scope["scope_id"], "页码")
    assert hits[0]["memory"]["kind"] == "criterion"

    assert seen[0].headers["authorization"] == "Bearer test-token"
    assert seen[0].method == "POST"
    assert json.loads(seen[0].content)["idempotency_key"] == "yj:samples/bib"


def test_commit_handoff_roundtrip(fake_powercontext) -> None:
    seen: list[httpx.Request] = []
    client = _client(fake_powercontext, seen)
    scope = client.ensure_scope("yj:samples/bib", "summary")
    entry = client.remember(scope["scope_id"], "decision", "claim-1 partial")[0]
    draft = {
        "objective": "继续核对草稿",
        "state": [{"text": "已完成 1 条主张", "citations": [entry.citation]}],
        "disposition": "continuable",
        "next_action": {"text": "复核 claim-1", "citations": [entry.citation]},
        "omissions": [],
    }

    committed, resolved = client.commit_handoff(scope["scope_id"], draft)
    assert committed["reference"]["revision"] == 1
    assert resolved.status == "resolved"
    assert resolved.trust == "untrusted_history"
    assert resolved.content == draft
    assert [request.url.path for request in seen][-3:] == [
        "/v1/handoff/finalize",
        "/v1/handoff/commit",
        "/v1/handoff/continue",
    ]


def test_list_entries_follows_cursor() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "cursor" not in body:
            return httpx.Response(
                200,
                json={
                    "entries": [
                        _entry_payload(MemoryEntry("art_1", 1, "criterion", "one", "active", 0))
                    ],
                    "next_cursor": "c1",
                },
            )
        return httpx.Response(
            200,
            json={
                "entries": [
                    _entry_payload(MemoryEntry("art_2", 1, "criterion", "two", "active", 0))
                ],
                "next_cursor": None,
            },
        )

    client = PowerContextClient(
        "http://pc.test",
        client=httpx.Client(transport=httpx.MockTransport(handler), timeout=1.0),
    )
    entries = client.list_entries("scp_1", limit=150)
    assert [entry.artifact_id for entry in entries] == ["art_1", "art_2"]
    assert [body["limit"] for body in bodies] == [100, 100]
    assert bodies[1]["cursor"] == "c1"


def test_list_entries_without_limit_reads_all_cursors() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        index = len(bodies)
        return httpx.Response(
            200,
            json={
                "entries": [
                    _entry_payload(
                        MemoryEntry(
                            f"art_{index}", 1, "criterion", f"entry {index}", "active", 0
                        )
                    )
                ],
                "next_cursor": f"c{index}" if index < 3 else None,
            },
        )

    client = PowerContextClient(
        "http://pc.test",
        client=httpx.Client(transport=httpx.MockTransport(handler), timeout=1.0),
    )
    entries = client.list_entries("scp_1", limit=None)
    assert [entry.artifact_id for entry in entries] == ["art_1", "art_2", "art_3"]
    assert [body["limit"] for body in bodies] == [100, 100, 100]
    assert [body.get("cursor") for body in bodies] == [None, "c1", "c2"]


def test_api_error_carries_status_and_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={"error": {"message": "The request violates the API contract.", "code": "invalid_request"}},
        )

    client = PowerContextClient(
        "http://pc.test",
        client=httpx.Client(transport=httpx.MockTransport(handler), timeout=1.0),
    )
    with pytest.raises(PowerContextError) as caught:
        client.list_entries("scp_1")
    assert caught.value.status_code == 422
    assert "invalid_request" in str(caught.value)
    assert "PowerContext" in (caught.value.hint or "")


def test_connection_error_mentions_docker() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = PowerContextClient(
        "http://pc.test",
        client=httpx.Client(transport=httpx.MockTransport(handler), timeout=1.0),
    )
    with pytest.raises(PowerContextError) as caught:
        client.ensure_scope("yj:x", "summary")
    assert "docker compose up -d powercontext" in (caught.value.hint or "")
