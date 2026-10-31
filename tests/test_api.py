import json
import threading
import time

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.api.routes import system as system_routes
from backend.api.services import memory as memory_service
from backend.api.services import uploads as uploads_service
from backend.core.config import Settings
from backend.diagnostics.checks import Check
from backend.evidence.store import EvidenceStore
from backend.memory.client import PowerContextError
from backend.runtime.providers import RuntimeConfigError


def _data(tmp_path):
    data = tmp_path / "data"
    samples = data / "samples"
    samples.mkdir(parents=True)
    (samples / "draft.md").write_text(
        "Alpha uses dense vectors for retrieval [@alpha].\n", encoding="utf-8"
    )
    (samples / "bib.json").write_text(
        json.dumps({"alpha": {"file": "alpha.pdf"}}), encoding="utf-8"
    )
    (samples / "alpha.pdf").write_bytes(b"%PDF-1.4\n")
    (samples / "labels.json").write_text(
        json.dumps({"name": "labels-v1", "items": [{"id": "s01", "label": "supported"}]}),
        encoding="utf-8",
    )
    return data


def _client(tmp_path, runner=None, frontend_dir=None, ingest_runner=None):
    settings = Settings(
        _env_file=None,
        data_dir=_data(tmp_path),
        frontend_dir=frontend_dir or tmp_path / "missing-frontend",
    )
    app = create_app(settings, runner=runner, ingest_runner=ingest_runner)
    return TestClient(app), settings


def _ingest_ok(spec, progress):
    progress({"stage": "ingest", "done": 0, "total": 1, "message": "正在解析 PDF"})
    return {
        "key": spec.ref.key,
        "status": "ingested",
        "page_count": 1,
        "para_count": 2,
        "sent_count": 3,
        "unit_count": 5,
    }


def _upload(client, body=b"%PDF-1.4\n%%EOF\n", **params):
    params.setdefault("filename", "paper.pdf")
    return client.post(
        "/api/uploads",
        params=params,
        content=body,
        headers={"Content-Type": "application/pdf"},
    )


def _audit_body(**overrides):
    body = {"draft": "samples/draft.md", "bib": "samples/bib.json"}
    body.update(overrides)
    return body


def _wait(client, job_id, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/api/jobs/{job_id}").json()["job"]
        if payload["status"] in {"succeeded", "failed"}:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish")


def test_config_and_unbuilt_frontend(tmp_path) -> None:
    client, _ = _client(tmp_path)
    config = client.get("/api/config").json()
    assert config["baseline"] is True
    assert config["memory_enabled"] is True
    assert config["frontend_built"] is False
    response = client.get("/")
    assert response.status_code == 404
    assert "前端尚未构建" in response.json()["message"]


def test_drafts_and_bibliographies_ignore_runtime(tmp_path) -> None:
    client, settings = _client(tmp_path)
    runtime = settings.data_dir / "runtime" / "reports" / "run-draft"
    runtime.mkdir(parents=True)
    (runtime / "report.json").write_text("{}", encoding="utf-8")

    drafts = client.get("/api/drafts").json()["drafts"]
    assert [item["path"] for item in drafts] == ["samples/draft.md"]
    assert "[@alpha]" in drafts[0]["content"]
    source = (settings.data_dir / "samples" / "draft.md").read_text(encoding="utf-8")
    assert drafts[0]["char_count"] == len(source)
    assert drafts[0]["line_count"] == 1
    assert drafts[0]["citation_count"] == 1
    assert drafts[0]["truncated"] is False

    bibliographies = client.get("/api/bibliographies").json()["bibliographies"]
    assert [item["path"] for item in bibliographies] == ["samples/bib.json"]


def test_draft_preview_reports_full_stats(tmp_path) -> None:
    client, settings = _client(tmp_path)
    body = ("filler " * 100 + "[@alpha]\n") * 40
    (settings.data_dir / "samples" / "long.md").write_text(body, encoding="utf-8")

    drafts = {item["path"]: item for item in client.get("/api/drafts").json()["drafts"]}
    item = drafts["samples/long.md"]
    assert item["truncated"] is True
    assert len(item["content"]) == 20000
    assert item["char_count"] == len(body)
    assert item["line_count"] == 40
    assert item["citation_count"] == 40


def test_audit_paths_stay_inside_data(tmp_path) -> None:
    client, settings = _client(tmp_path)
    (tmp_path / "secret.md").write_text("secret [@alpha]", encoding="utf-8")
    (settings.data_dir / "samples" / "notes.txt").write_text("notes", encoding="utf-8")

    outside = client.post("/api/audits", json=_audit_body(draft="../secret.md"))
    assert outside.status_code == 400
    assert "数据目录内" in outside.json()["detail"]["message"]

    wrong_type = client.post("/api/audits", json=_audit_body(draft="samples/notes.txt"))
    assert wrong_type.status_code == 400
    assert "文件类型" in wrong_type.json()["detail"]["message"]

    missing = client.post("/api/audits", json=_audit_body(draft="samples/missing.md"))
    assert missing.status_code == 400
    assert "找不到文件" in missing.json()["detail"]["message"]


def test_job_succeeds_with_progress(tmp_path) -> None:
    reached = threading.Event()
    release = threading.Event()

    def runner(spec, progress):
        progress({"stage": "preflight", "done": 0, "total": 2, "message": "校验通过"})
        progress(
            {
                "stage": "claim",
                "done": 1,
                "total": 2,
                "claim_id": "claim-01",
                "message": "第一条完成",
            }
        )
        reached.set()
        release.wait(2)
        return {"run_id": "run-1", "summary": {"claims": 1}}

    client, _ = _client(tmp_path, runner=runner)
    response = client.post("/api/audits", json=_audit_body())
    assert response.status_code == 202
    assert reached.wait(2)
    running = client.get(f"/api/jobs/{response.json()['job']['id']}").json()["job"]
    assert running["status"] == "running"
    assert running["claim_id"] == "claim-01"
    assert 2 < running["progress"] < 100
    release.set()
    job = _wait(client, response.json()["job"]["id"])
    assert job["status"] == "succeeded"
    assert job["progress"] == 100
    assert job["result"]["run_id"] == "run-1"
    assert job["claim_id"] is None


def test_job_failure_exposes_runtime_hint(tmp_path) -> None:
    def runner(spec, progress):
        raise RuntimeConfigError("seekdb unavailable", "docker compose up -d seekdb")

    client, _ = _client(tmp_path, runner=runner)
    response = client.post("/api/audits", json=_audit_body())
    job = _wait(client, response.json()["job"]["id"])
    assert job["status"] == "failed"
    assert job["error"] == "RuntimeConfigError: seekdb unavailable"
    assert job["hint"] == "docker compose up -d seekdb"


def test_only_one_job_runs_at_a_time(tmp_path) -> None:
    started = threading.Event()
    release = threading.Event()

    def runner(spec, progress):
        started.set()
        release.wait(2)
        return {"run_id": "slow"}

    client, _ = _client(tmp_path, runner=runner)
    first = client.post("/api/audits", json=_audit_body())
    assert first.status_code == 202
    assert started.wait(2)
    second = client.post("/api/audits", json=_audit_body())
    assert second.status_code == 409
    release.set()
    assert _wait(client, first.json()["job"]["id"])["status"] == "succeeded"


def test_papers_reports_health_and_static(tmp_path) -> None:
    reports = (
        tmp_path
        / "data"
        / "runtime"
        / "reports"
        / "20261026T120000000000Z-draft"
    )
    reports.mkdir(parents=True)
    payload = {
        "run_id": "20261026T120000000000Z",
        "generated_at": "2026-10-26T12:00:00+00:00",
        "draft": "samples/draft.md",
        "bib": "samples/bib.json",
        "verifier": "none/baseline",
        "summary": {"claims": 1, "citations": 1},
        "warnings": [],
        "claims": [],
    }
    (reports / "report.json").write_text(json.dumps(payload), encoding="utf-8")
    (reports / "report.md").write_text("# report\n", encoding="utf-8")
    (reports / "report.csv").write_bytes(b"a,b\n")
    (reports / "memory.json").write_text(
        json.dumps({"ok": True, "written": 3, "handoff": {"revision": 1}}), encoding="utf-8"
    )

    dist = tmp_path / "web"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('app')", encoding="utf-8")

    client, _ = _client(tmp_path, frontend_dir=dist)

    listed = client.get("/api/reports").json()["reports"]
    assert [item["run_id"] for item in listed] == ["20261026T120000000000Z"]
    assert listed[0]["downloads"]["markdown"].endswith("/download/markdown")

    detail = client.get("/api/reports/20261026T120000000000Z").json()
    assert detail["downloads"]["json"].endswith("/download/json")
    assert detail["memory"]["ok"] is True
    assert detail["memory"]["handoff"]["revision"] == 1
    download = client.get("/api/reports/20261026T120000000000Z/download/csv")
    assert download.status_code == 200
    assert download.content == b"a,b\n"

    assert client.get("/api/reports/unknown").status_code == 404
    assert client.get("/api/reports/unknown/download/markdown").status_code == 404
    assert client.get(
        "/api/reports/20261026T120000000000Z/download/pdf"
    ).status_code == 404

    assert client.get("/").text == "<html>app</html>"
    assert client.get("/assets/app.js").text == "console.log('app')"
    assert client.get("/reports/20261026T120000000000Z").text == "<html>app</html>"
    assert client.get("/api/nope").status_code == 404

    checks = [
        Check("data", True, "ok"),
        Check("powercontext", False, "down", "start it"),
    ]
    original = system_routes.run_checks
    system_routes.run_checks = lambda settings: checks
    try:
        health = client.get("/api/health").json()
    finally:
        system_routes.run_checks = original
    assert health["ok"] is False
    assert health["checks"][1]["hint"] == "start it"


def test_papers_surfaces_seekdb_failure(tmp_path, monkeypatch) -> None:
    client, _ = _client(tmp_path)

    def boom(self):
        raise RuntimeError("db down")

    monkeypatch.setattr(EvidenceStore, "list_papers", boom)
    response = client.get("/api/papers")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["message"].startswith("seekdb 不可用：RuntimeError: db down")
    assert "citationproof ingest" in detail["hint"]


def test_memory_endpoints_roundtrip(tmp_path, monkeypatch, fake_powercontext) -> None:
    client, _ = _client(tmp_path)
    monkeypatch.setattr(memory_service, "_powercontext_client", lambda settings: fake_powercontext)

    projects = client.get("/api/memory/projects").json()
    assert projects["default"] == "samples/bib"
    assert [item["project"] for item in projects["projects"]] == ["samples/bib"]
    assert projects["projects"][0]["scope_id"] is None

    empty = client.get("/api/memory").json()
    assert empty["project"] == "samples/bib"
    assert empty["scope"]["title"] == "cd:samples/bib"
    assert empty["handoff"]["status"] == "empty"
    assert empty["entries"] == []

    written = client.post(
        "/api/memory/entries",
        json={
            "project": "samples/bib",
            "kind": "criterion",
            "text": "引用必须给出页码",
            "reason": "entry from test",
        },
    )
    assert written.status_code == 200
    assert written.json()["changed"] is True
    assert written.json()["records"][0]["artifact_id"] == "art_1"
    assert fake_powercontext.last_remember["reason"] == "entry from test"

    duplicate = client.post(
        "/api/memory/entries",
        json={
            "project": "samples/bib",
            "kind": "criterion",
            "text": "引用必须给出页码",
            "reason": "entry from test",
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["changed"] is False
    assert duplicate.json()["records"] == []
    assert fake_powercontext.last_remember["reason"] == "entry from test"

    listed = client.get("/api/memory", params={"kind": "criterion"}).json()
    assert listed["total"] == 1
    assert listed["counts"]["criterion"] == 1
    assert listed["entries"][0]["text"] == "引用必须给出页码"

    search = client.get("/api/memory/search", params={"q": "页码"}).json()
    assert search["hits"][0]["memory"]["kind"] == "criterion"

    continued = client.post(
        "/api/memory/handoff/continue", json={"project": "samples/bib"}
    ).json()
    assert continued["handoff"]["status"] == "empty"

    projects = client.get("/api/memory/projects").json()
    assert projects["projects"][0]["scope_id"] == "scp_1"


def test_memory_endpoint_pages_past_previous_cap(
    tmp_path, monkeypatch, fake_powercontext
) -> None:
    client, _ = _client(tmp_path)
    monkeypatch.setattr(memory_service, "_powercontext_client", lambda settings: fake_powercontext)
    scope = fake_powercontext.ensure_scope("cd:samples/bib", "引据项目 samples/bib")
    for index in range(620):
        fake_powercontext.remember(scope["scope_id"], "criterion", f"标准 {index}")
    for index in range(3):
        fake_powercontext.remember(scope["scope_id"], "decision", f"判断 {index}")

    first = client.get("/api/memory").json()
    assert first["total"] == 623
    assert first["offset"] == 0
    assert first["limit"] == 20
    assert len(first["entries"]) == 20
    assert first["has_more"] is True
    assert first["counts"]["criterion"] == 620
    assert first["counts"]["decision"] == 3

    tail = client.get(
        "/api/memory", params={"kind": "criterion", "limit": 200, "offset": 600}
    ).json()
    assert tail["total"] == 620
    assert tail["offset"] == 600
    assert len(tail["entries"]) == 20
    assert tail["has_more"] is False
    assert tail["entries"][-1]["text"] == "标准 619"

    past = client.get("/api/memory", params={"offset": 9999}).json()
    assert past["entries"] == []
    assert past["total"] == 623
    assert past["has_more"] is False

    capped = client.get("/api/memory", params={"limit": 9999}).json()
    assert capped["limit"] == 200
    assert len(capped["entries"]) == 200


def test_memory_endpoints_validate_input(tmp_path, monkeypatch, fake_powercontext) -> None:
    client, _ = _client(tmp_path)
    monkeypatch.setattr(memory_service, "_powercontext_client", lambda settings: fake_powercontext)

    bad_kind = client.post(
        "/api/memory/entries",
        json={"project": "samples/bib", "kind": "note", "text": "x"},
    )
    assert bad_kind.status_code == 400
    assert "记忆类型必须是以下之一" in bad_kind.json()["detail"]["message"]

    bad_project = client.get("/api/memory", params={"project": "../escape"})
    assert bad_project.status_code == 400
    assert "项目名" in bad_project.json()["detail"]["message"]

    empty_query = client.get("/api/memory/search", params={"q": " "})
    assert empty_query.status_code == 400


def test_memory_surfaces_powercontext_failure(tmp_path, monkeypatch) -> None:
    client, _ = _client(tmp_path)

    class Broken:
        def list_scopes(self, prefix: str = "cd:") -> list[dict]:
            raise PowerContextError("connection refused", "docker compose up -d powercontext")

        def close(self) -> None:
            pass

    monkeypatch.setattr(memory_service, "_powercontext_client", lambda settings: Broken())
    response = client.get("/api/memory/projects")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "connection refused" in detail["message"]
    assert detail["hint"] == "docker compose up -d powercontext"


def test_upload_pdf_registers_bibliography_and_ingests(tmp_path) -> None:
    calls = []

    def ingest_runner(spec, progress):
        calls.append(spec.ref)
        progress({"stage": "ingest", "done": 0, "total": 2, "message": "正在生成向量"})
        progress({"stage": "ingest", "done": 1, "total": 2, "message": "正在生成向量 1/2 批"})
        return _ingest_ok(spec, progress)

    client, settings = _client(tmp_path, ingest_runner=ingest_runner)
    response = _upload(
        client,
        filename="Photon SIGMOD.pdf",
        title="Photon: A Fast Query Engine",
        authors="Alexander Behm et al.",
        year=2022,
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["duplicate"] is False
    paper = payload["paper"]
    assert paper["key"].startswith("upload-photon-sigmod-")
    assert paper["title"] == "Photon: A Fast Query Engine"
    assert paper["year"] == 2022

    job = _wait(client, payload["job"]["id"])
    assert job["status"] == "succeeded"
    assert job["kind"] == "ingest"
    assert job["paper_key"] == paper["key"]
    assert job["message"] == "入库完成"
    assert job["result"]["unit_count"] == 5
    assert job["result"]["key"] == paper["key"]

    target = settings.data_dir / "uploads" / "papers" / f"{paper['key']}.pdf"
    assert target.read_bytes().startswith(b"%PDF-")
    bib = json.loads((settings.data_dir / "uploads" / "bib.json").read_text(encoding="utf-8"))
    assert bib[paper["key"]]["file"] == f"papers/{paper['key']}.pdf"
    assert bib[paper["key"]]["authors"] == "Alexander Behm et al."

    bibliographies = client.get("/api/bibliographies").json()["bibliographies"]
    assert "uploads/bib.json" in [item["path"] for item in bibliographies]
    listed = client.get("/api/jobs").json()["jobs"]
    assert listed[0]["kind"] == "ingest"
    assert [ref.key for ref in calls] == [paper["key"]]


def test_upload_rejects_bad_payloads(tmp_path, monkeypatch) -> None:
    client, settings = _client(tmp_path, ingest_runner=_ingest_ok)

    not_pdf = _upload(client, body=b"<html>not a pdf</html>")
    assert not_pdf.status_code == 400
    assert "%PDF-" in not_pdf.json()["detail"]["message"]

    wrong_type = client.post(
        "/api/uploads",
        params={"filename": "paper.pdf"},
        content=b"%PDF-1.4\n",
        headers={"Content-Type": "application/json"},
    )
    assert wrong_type.status_code == 415

    empty = _upload(client, body=b"")
    assert empty.status_code == 400

    monkeypatch.setattr(uploads_service, "MAX_UPLOAD_BYTES", 64)
    too_big = _upload(client, body=b"%PDF-1.4\n" + b"x" * 100)
    assert too_big.status_code == 413
    assert "不能超过" in too_big.json()["detail"]["message"]
    assert not (settings.data_dir / "uploads" / "papers").exists()


def test_upload_filename_cannot_escape_uploads(tmp_path) -> None:
    client, settings = _client(tmp_path, ingest_runner=_ingest_ok)
    response = _upload(client, filename="../../evil.pdf")
    assert response.status_code == 202
    paper = response.json()["paper"]
    assert paper["key"].startswith("upload-evil-")
    paths = list((settings.data_dir / "uploads").rglob("*.pdf"))
    assert len(paths) == 1
    assert paths[0].parent.name == "papers"
    assert not (tmp_path / "evil.pdf").exists()


def test_reupload_same_pdf_is_idempotent(tmp_path) -> None:
    seen = []

    def ingest_runner(spec, progress):
        seen.append(spec.ref.key)
        return _ingest_ok(spec, progress)

    client, settings = _client(tmp_path, ingest_runner=ingest_runner)
    body = b"%PDF-1.4\nsame bytes\n"
    first = _upload(client, body=body, filename="first.pdf").json()
    _wait(client, first["job"]["id"])
    second = _upload(client, body=body, filename="renamed.pdf").json()

    assert second["duplicate"] is True
    assert second["paper"]["key"] == first["paper"]["key"]
    assert second["job"]["status"] in {"queued", "running", "succeeded"}
    _wait(client, second["job"]["id"])
    assert seen == [first["paper"]["key"], first["paper"]["key"]]
    bib = json.loads((settings.data_dir / "uploads" / "bib.json").read_text(encoding="utf-8"))
    assert len(bib) == 1


def test_upload_conflicts_with_running_ingest(tmp_path) -> None:
    started = threading.Event()
    release = threading.Event()

    def ingest_runner(spec, progress):
        started.set()
        release.wait(2)
        return _ingest_ok(spec, progress)

    client, settings = _client(tmp_path, ingest_runner=ingest_runner)
    first = _upload(client, body=b"%PDF-1.4\none\n", filename="one.pdf")
    assert first.status_code == 202
    assert started.wait(2)
    second = _upload(client, body=b"%PDF-1.4\ntwo\n", filename="two.pdf")
    assert second.status_code == 409
    assert "入库任务" in second.json()["detail"]["message"]
    release.set()
    assert _wait(client, first.json()["job"]["id"])["status"] == "succeeded"
    bib = json.loads((settings.data_dir / "uploads" / "bib.json").read_text(encoding="utf-8"))
    assert len(bib) == 1


def test_upload_reports_runtime_hint(tmp_path) -> None:
    def ingest_runner(spec, progress):
        raise RuntimeConfigError("seekdb unavailable", "docker compose up -d seekdb")

    client, _ = _client(tmp_path, ingest_runner=ingest_runner)
    response = _upload(client)
    job = _wait(client, response.json()["job"]["id"])
    assert job["status"] == "failed"
    assert job["hint"] == "docker compose up -d seekdb"
