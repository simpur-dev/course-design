from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self

import httpx

SCOPE_PREFIX = "yj:"
MEMORY_KINDS = ("criterion", "decision", "constraint", "next_step")


class PowerContextError(RuntimeError):
    def __init__(
        self,
        message: str,
        hint: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.hint = hint
        self.status_code = status_code


@dataclass(frozen=True)
class MemoryEntry:
    artifact_id: str
    revision: int
    kind: str
    text: str
    state: str
    state_version: int

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> MemoryEntry:
        artifact = payload.get("artifact") or {}
        return cls(
            artifact_id=str(artifact.get("artifact_id", "")),
            revision=int(artifact.get("revision", 0)),
            kind=str(payload.get("kind", "")),
            text=str(payload.get("text", "")),
            state=str(payload.get("state", "")),
            state_version=int(payload.get("state_version", 0)),
        )

    @property
    def citation(self) -> dict[str, Any]:
        return {
            "kind": "artifact",
            "artifact_ref": {
                "family": "atomic-memory",
                "artifact_id": self.artifact_id,
                "revision": self.revision,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "revision": self.revision,
            "kind": self.kind,
            "text": self.text,
            "state": self.state,
            "state_version": self.state_version,
        }


@dataclass(frozen=True)
class HandoffView:
    status: str
    trust: str
    content: dict[str, Any] | None
    evidence_checks: tuple[dict[str, Any], ...]
    selected_revision: dict[str, Any] | None
    current_revision: dict[str, Any] | None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> HandoffView:
        return cls(
            status=str(payload.get("status", "")),
            trust=str(payload.get("trust", "")),
            content=payload.get("content") or None,
            evidence_checks=tuple(payload.get("evidence_checks") or ()),
            selected_revision=payload.get("selected_revision") or None,
            current_revision=payload.get("current_revision") or None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "trust": self.trust,
            "content": self.content,
            "evidence_checks": list(self.evidence_checks),
            "selected_revision": self.selected_revision,
            "current_revision": self.current_revision,
        }


class PowerContextClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def ensure_scope(self, title: str, summary: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/scopes",
            {"title": title, "summary": summary, "idempotency_key": title},
        )

    def list_scopes(self, prefix: str = SCOPE_PREFIX) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            page = self._request("GET", "/v1/scopes", params=params)
            for item in page.get("items") or ():
                if str(item.get("title", "")).startswith(prefix):
                    items.append(item)
            cursor = page.get("next_cursor")
            if not cursor:
                return items

    def remember(
        self,
        scope_id: str,
        kind: str,
        text: str,
        reason: str | None = None,
    ) -> list[MemoryEntry]:
        payload: dict[str, Any] = {"scope_id": scope_id, "kind": kind, "text": text}
        if reason:
            payload["reason"] = reason
        response = self._request("POST", "/v1/memory/remember", payload)
        return [MemoryEntry.from_payload(item) for item in response.get("records") or ()]

    def list_entries(
        self, scope_id: str, limit: int | None = 200
    ) -> list[MemoryEntry]:
        entries: list[MemoryEntry] = []
        cursor: str | None = None
        while limit is None or len(entries) < limit:
            batch = 100 if limit is None else min(100, limit - len(entries))
            payload: dict[str, Any] = {"scope_id": scope_id, "limit": batch}
            if cursor:
                payload["cursor"] = cursor
            response = self._request("POST", "/v1/memory/entries/list", payload)
            entries.extend(
                MemoryEntry.from_payload(item) for item in response.get("entries") or ()
            )
            cursor = response.get("next_cursor")
            if not cursor:
                break
        return entries if limit is None else entries[:limit]

    def search(
        self,
        scope_id: str,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        response = self._request(
            "POST",
            "/v1/memory/search",
            {"scope_id": scope_id, "query": query, "limit": limit, "mode": "auto"},
        )
        return list(response.get("hits") or ())

    def commit_handoff(
        self,
        scope_id: str,
        draft: dict[str, Any],
    ) -> tuple[dict[str, Any], HandoffView]:
        prepared = self._request(
            "POST",
            "/v1/handoff/finalize",
            {"scope_id": scope_id, "draft": draft},
        )
        committed = self._request(
            "POST",
            "/v1/handoff/commit",
            {"scope_id": scope_id, "handoff": prepared},
        )
        return committed, self.continue_handoff(scope_id)

    def continue_handoff(self, scope_id: str, selection: str = "latest") -> HandoffView:
        response = self._request(
            "POST",
            "/v1/handoff/continue",
            {"scope_id": scope_id, "selection": selection},
        )
        return HandoffView.from_payload(response)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            headers = {"Authorization": f"Bearer {self._token}"} if self._token else None
            response = self._client.request(
                method,
                f"{self.base_url}{path}",
                json=payload,
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise PowerContextError(
                f"PowerContext unavailable at {self.base_url}: {type(exc).__name__}: {exc}",
                "docker compose up -d powercontext；检查 YINJU_POWERCONTEXT_PORT",
            ) from exc
        if response.status_code >= 400:
            message, code = self._error_message(response)
            raise PowerContextError(
                f"{message} (HTTP {response.status_code}{', ' + code if code else ''})",
                "检查 PowerContext 日志；可在 #/system 查看自检结果",
                response.status_code,
            )
        if not response.content:
            return {}
        try:
            body = response.json()
        except ValueError as exc:
            raise PowerContextError(
                f"PowerContext returned non-JSON at {path}",
                "检查 YINJU_POWERCONTEXT_PORT 是否指向 PowerContext",
            ) from exc
        return body if isinstance(body, dict) else {}

    @staticmethod
    def _error_message(response: httpx.Response) -> tuple[str, str | None]:
        try:
            body = response.json()
        except ValueError:
            return response.text.strip()[:300] or "PowerContext request failed", None
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            message = str(error.get("message") or "PowerContext request failed")
            code = error.get("code")
            return message, str(code) if code else None
        detail = body.get("detail") if isinstance(body, dict) else None
        return str(detail or "PowerContext request failed"), None
