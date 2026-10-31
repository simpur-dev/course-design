# 接口与模块契约

本文定义重构后仓库的**稳定边界**：谁依赖谁、哪些名字是公共接口、JSON 长什么样、测试锁定了哪些替换点。改动跨模块接口时，先改本文，再改代码与测试。

## 1. 全局约束

### 1.1 分层与依赖方向

```text
core ──► evidence ──► audit ──► agent ──► api / cli
                │        │         │
                │        └──► memory
                └──► runtime ──────┘
diagnostics ──► core
```

- `core`：只放配置与常量型基础能力，不导入其他业务包。
- `evidence`：PDF 解析、证据单元、向量缓存、seekdb 访问。
- `audit`：草稿解析、检索编排、判定器、报告与评测。
- `memory`：PowerContext 客户端与报告 → Scope/Handoff 的同步。
- `runtime`：任务管理器、外部依赖构建（embedder/store/cache/verifier）、入库管线。
- `agent`：执行 Agent 的落点，当前是固定核对管线；只编排，不复制底层实现。
- `api` / `cli`：协议适配层；不承载业务规则。
- `diagnostics`：只读自检，不修改数据。

禁止反向导入（例如 `audit` 导入 `api`）。`api/services` 之间可以复用，`api/routes` 只调用 service 与 `deps`。

### 1.2 技术标识

| 项 | 取值 | 位置 |
| --- | --- | --- |
| Python 包 | `backend` | `pyproject.toml`、所有 import |
| 发行名 | `course-design-backend` | `pyproject.toml` |
| CLI 命令 | `citationproof` | `[project.scripts]` |
| 环境变量前缀 | `APP_` | `backend/core/config.py` |
| 默认 seekdb 库 | `course_design` | `Settings.seekdb_database` |
| 记忆 Scope 前缀 | `cd:` | `backend/memory/client.py` |
| 前端目录 | `frontend/`，产物 `frontend/dist/` | `Settings.frontend_dir` |

`python -m backend` 与 `uv run citationproof` 等价。

## 2. 后端公共接口

以下名字从包根的 `__all__` 导出，是三人协作的稳定面；子模块内部辅助函数不承诺兼容。

### 2.1 `backend.core`

```python
class Settings(BaseSettings):
    # 环境变量前缀 APP_，读取仓库根目录 .env（可被 _env_file=None 关闭）
    seekdb_host: str; seekdb_port: int; seekdb_user: str
    seekdb_password: SecretStr; seekdb_database: str
    powercontext_host: str; powercontext_port: int
    powercontext_token: SecretStr | None; powercontext_timeout: float
    memory_enabled: bool
    embedding_provider: Literal["local", "openai", "none"]
    verifier_provider: Literal["none", "openai", "anthropic"]
    verifier_model: str; verifier_timeout: float
    openai_api_key: SecretStr | None; openai_base_url: str | None
    anthropic_api_key: SecretStr | None; anthropic_base_url: str | None
    data_dir: Path; frontend_dir: Path
    server_host: str; server_port: int; log_level: str

    @property
    def powercontext_base_url(self) -> str: ...
```

### 2.2 `backend.evidence`

**数据对象**

| 类型 | 关键字段 |
| --- | --- |
| `PaperRef` | `key`、`file: Path`、`title`、`authors`、`year`、`source_url` |
| `EvidenceUnit` | `unit_id`、`paper_key`、`page`、`unit_type`（`para`/`sent`）、`unit_index`、`parent_id`、`text` |
| `ParsedPaper` | `paper_key`、`page_count`、`para_count`、`sent_count`、`units` |
| `SearchHit` | `unit_id`、`paper_key`、`page`、`unit_type`、`text`、`distance`、`parent_id` |
| `HybridHit` | `unit_id`、`paper_key`、`page`、`unit_type`、`text`、`score`、`cosine`、`keyword_coverage`、`number_status`、`fulltext_rank`、`vector_rank` |
| `PaperRecord` | 论文元数据、SHA-256、页数、段/句计数、`unit_mode`、`ingested_at` |
| `EmbedResult` | `vectors`、`embedded`、`computed`、`cached`、`batches` |
| `IngestResult` | `key`、`status`（`ingested`/`updated`/`skipped`）、计数、耗时、`to_dict()` |

**函数**

```python
load_bibliography(path: Path) -> dict[str, PaperRef]
parse_pdf(path: Path, paper_key: str) -> ParsedPaper          # 抛 PdfParseError
units_from_pages(pages, paper_key) -> ParsedPaper
file_sha256(path: Path) -> str
embedding_model_id(embedder) -> str
embedding_dimension(embedder) -> int | None
ingest_paper(ref, store, cache, force=False, batch_size=64, on_progress=None) -> IngestResult
ingest_bibliography(refs, store, cache, keys=None, force=False, ...) -> list[IngestResult]
```

**`EvidenceStore`**

```python
EvidenceStore(settings, embedder=None)     # embedder 为 None 时只读元数据
.ensure() -> EvidenceStore
.get_paper(key) / .list_papers() / .upsert_paper(record)
.replace_units(key, units, vectors)        # 事务内替换该论文全部单元
.search(query, paper_key, unit_type="sent", limit=5) -> list[SearchHit]
.hybrid_search(query_embedding, keywords, paper_key, unit_type="para",
               limit=5, per_leg=20, rrf_k=60) -> list[HybridHit]
.fetch_units(unit_ids) / .fetch_children(parent_ids)
```

集合固定为 `evidence_units`；单元 ID 为 `{key}:p{page}:para{n}` / `{key}:p{page}:sent{n}`。检索必须带 `paper_key` 过滤，这是核对架构的核心不变量。

### 2.3 `backend.audit`

**草稿与主张**

```python
parse_draft(path: Path) -> list[Claim]      # Claim: claim_id/text/line_start/line_end/citations
```

**判定器协议**

```python
class Verifier(Protocol):
    name: str
    def verify(self, claim: str, candidates: Sequence[Evidence]) -> Verdict: ...

@dataclass
class Verdict:
    verdict: str          # supported / partial / unsupported / unknown
    confidence: str       # low / medium / high
    review_required: bool
    reason: str
    evidence_id: str | None
```

- `BaselineVerifier`：无 key 基线，永不出具 `supported`。
- `ChatVerifier`：OpenAI/Anthropic 适配器；模型返回的 `evidence_id` 不在候选集合时该条判 `unknown`。
- 新增判定器只需实现 `Verifier`，在 `backend/runtime/providers.py::build_verifier` 注册。

**核对引擎**

```python
AuditEngine(store, cache, verifier, embedding_model,
            paragraph_limit=5, per_leg=20, candidate_limit=8)
.audit(claims, refs, draft_path, bib_path, on_progress=None) -> AuditReport
```

`AuditReport` 字段：`run_id`、`generated_at`、`draft_path`、`bib_path`、`verifier`、`embedding_model`、`unit_mode`、`claims: list[ClaimCheck]`、`warnings`。`ClaimCheck` 含 `claim`、`verdict`、`checks`、`seconds`；`CitationCheck` 含被引论文、四档结论、置信度、理由、关键词、数字状态、原句 `Evidence`、段落候选与句候选。

**报告**

```python
report_to_dict(report) / report_to_markdown(report) / report_to_csv(report)
write_reports(report, out_dir: Path) -> dict[Literal["md","csv","json"], Path]
```

`report.json` 顶层契约：

```json
{
  "run_id": "20261031T...",
  "generated_at": "...",
  "draft": "data/samples/draft.md",
  "bib": "data/samples/bib.json",
  "verifier": "none/baseline",
  "embedding_model": "...",
  "unit_mode": "para",
  "summary": {
    "claims": 1, "citations": 1,
    "claim_verdicts": {"supported": 0, "partial": 1, "unsupported": 0, "unknown": 0},
    "citation_verdicts": {"...": 0},
    "review_required": 1, "errors": 0
  },
  "warnings": [],
  "claims": []
}
```

Web 运行还会在报告目录额外写 `memory.json`，并把 `files` 与 `downloads` 注入接口响应；磁盘上的 `report.json` 不含这两个派生字段。

**评测**

`load_labeled_set`、`evaluate`、`compute_metrics`、`evaluation_to_dict`、`evaluation_to_markdown`、`write_evaluation` 供 `citationproof eval` 使用；标注集格式见 `data/samples/labels.json`。

### 2.4 `backend.memory`

```python
SCOPE_PREFIX = "cd:"

class PowerContextClient:
    ensure_scope(title, summary) -> dict
    list_scopes(prefix=SCOPE_PREFIX) -> list[dict]
    remember(scope_id, kind, text, reason=None) -> list[MemoryEntry]
    list_entries(scope_id, limit=200) -> list[MemoryEntry]
    search(scope_id, query, limit=10) -> list[dict]
    commit_handoff(scope_id, draft) -> tuple[dict, HandoffView]
    continue_handoff(scope_id, selection="latest") -> HandoffView
    close() / with PowerContextClient(...) as client

sync_report_memory(settings, report, bib_path) -> MemorySyncResult
sync_with_client(client, project, report) -> MemorySyncResult
```

- 记忆类型固定为 `criterion` / `decision` / `constraint` / `next_step`。
- Scope 标题：`cd:{bib 相对 data/ 的路径去后缀}`，例如 `cd:samples/bib`。
- 标准与约束按 `(kind, text)` 去重；判断按 `run_id` 追加；Handoff 幂等。
- `MemorySyncResult.ok=False` 不阻断核对，报告照常生成；错误与 hint 写入 `memory.json`。

### 2.5 `backend.agent`

```python
class AuditAgent:
    def __init__(self, settings: Settings) -> None: ...
    def run(self, spec: RunSpec, progress: ProgressCallback) -> dict[str, Any]: ...

run_audit(settings, spec, progress) -> dict[str, Any]
```

`run_audit` 的返回值是**报告 JSON 的可扩展超集**：`report_to_dict` 的全部字段 + `files` + `memory`。目标 v5 的风险分诊、策略规划、有界 ReAct、人工复核闸门都应落在 `AuditAgent` 内部；`api/cli` 不感知策略细节。

### 2.6 `backend.runtime`

| 类型 | 契约 |
| --- | --- |
| `RunSpec` | `draft: Path`、`bib: Path`、`paragraphs: int`、`per_leg: int` |
| `IngestSpec` | `ref: PaperRef` |
| `Job` | `id/status/stage/progress/message/claim_id/result/error/hint/kind/paper_key`，状态机 `queued → running → succeeded|failed` |
| `JobManager` | `submit(spec, kind=..., ...)` 单任务互斥，忙时抛 `JobBusy`；`get/snapshot/recent/busy` |
| `RuntimeConfigError` | `str` 为错误，`hint` 给用户下一步 |

```python
build_embedder(settings) / open_store(settings, embedder) / open_cache(settings, embedder)
build_verifier(settings)
run_ingest(settings, spec, progress) -> dict
```

### 2.7 `backend.diagnostics`

```python
Check(name, ok, detail, hint=None)
check_data_dir / check_seekdb / check_powercontext / check_providers
run_checks(settings) -> list[Check]
```

### 2.8 HTTP API（`backend.api.create_app`）

`create_app(settings=None, runner=None, ingest_runner=None)` 注入 runner 供测试替换；默认 runner 为 `AuditAgent` / `run_ingest`。`AppContext`（`app.state.context`）持有 `settings/data_root/reports_root/frontend_root/audit_jobs/ingest_jobs/upload_lock`。

| 方法 | 路径 | 请求 | 成功 | 主要错误 |
| --- | --- | --- | --- | --- |
| GET | `/api/config` | — | 版本、判定器、`frontend_built` | — |
| GET | `/api/health` | — | `{ok, checks[]}` | — |
| GET | `/api/papers` | — | `{papers[], count}` | 503 + hint |
| GET | `/api/drafts` | — | `{drafts[]}`（预览 ≤ 20000 字符，计数按全文） | — |
| GET | `/api/bibliographies` | — | `{bibliographies[]}` | — |
| POST | `/api/uploads` | query `filename/title/authors/year` + PDF body | 202 `{job, paper, duplicate}` | 400/409/413/415 |
| POST | `/api/audits` | `AuditRequest` | 202 `{job}` | 400 路径/类型，409 忙 |
| GET | `/api/jobs` | — | `{jobs[]}` 按创建时间倒序 | — |
| GET | `/api/jobs/{id}` | — | `{job}` | 404 |
| GET | `/api/reports` | — | `{reports[]}` | — |
| GET | `/api/reports/{run_id}` | — | 报告 JSON + `downloads` + `memory` | 404 |
| GET | `/api/reports/{run_id}/download/{kind}` | `markdown/csv/json` | 文件流 | 404 |
| GET | `/api/memory/projects` | — | `{projects[], default, kinds[]}` | 503 |
| GET | `/api/memory` | `project/kind/limit/offset` | 分页 + `total/counts/has_more/handoff` | 400/503 |
| GET | `/api/memory/search` | `q` 非空 ≤ 500 字符 | `{hits[]}` | 400/503 |
| POST | `/api/memory/entries` | `MemoryWriteRequest` | `{changed, records[]}` | 400/503 |
| POST | `/api/memory/handoff/continue` | `{project}` | `{handoff}` | 400/503 |

错误体统一为 `{"detail": {"message": "...", "hint": "..."}}`；前端 `ApiError` 消费这两个字段。

### 2.9 CLI（`backend.cli`）

命令：`version`、`serve`、`doctor`、`ingest`、`papers`、`search`、`audit`、`eval`。全局 `-v/--verbose`。命令实现位于 `backend/cli/commands/<name>.py`，每个模块暴露 `register(app)`；新增命令时在 `backend/cli/main.py` 注册一次。

退出码：成功 `0`；自检失败、核对存在 error、配置/IO 错误为 `1`；`typer` 用法错误为 `2`。

## 3. 前端契约

```text
app/      应用外壳：路由解析、路由注册表、导航、全局状态、样式
shared/   api/client、api/endpoints、types、format、通用 hooks
features/ audit、papers、reports、memory、system
```

- 路由状态是判别联合 `RouteState`（`app/router.ts`）；新增路由必须同时更新 `parseRoute`、`resolveRoute`，需要主导航时再更新 `NAV_ITEMS`。
- 页面只通过 `shared/api` 访问后端；不得直接 `fetch`。
- feature 之间只允许 `audit → reports`（复用 `ReportView`），其余跨 feature 依赖必须先上移到 `shared`。
- `shared/types.ts` 与后端 JSON 契约一一对应；后端改字段时同步修改前端类型与页面。
- 样式为单一样式表 `app/styles/index.css`；新增页面的类名放在对应区块，避免互相覆盖。

## 4. 测试契约

默认测试不依赖外部服务：

```bash
uv run pytest
uv run ruff check .
npm --prefix frontend run lint
npm --prefix frontend run build
```

被测试显式替换的名字是接口的一部分，移动实现时必须同步更新测试：

| 测试替换点 | 用途 |
| --- | --- |
| `backend.api.services.memory._powercontext_client` | 注入 Fake PowerContext |
| `backend.api.services.uploads.MAX_UPLOAD_BYTES` | 上传上限 |
| `backend.api.routes.system.run_checks` | 健康检查 |
| `backend.cli.main.Settings` | CLI 配置 |
| `backend.cli.commands.doctor.run_checks` | CLI 自检 |
| `backend.memory.sync.PowerContextClient` | 记忆同步失败路径 |
| `backend.diagnostics.checks.pymysql.connect` | seekdb 自检 |
| `backend.audit.verdicts.httpx.post` | LLM 判定器 |

集成测试默认跳过，显式开启：

```bash
APP_TEST_SEEKDB=1 APP_SEEKDB_PORT=2881 uv run pytest tests/test_integration_seekdb.py tests/test_integration_audit.py
APP_TEST_POWERCONTEXT_URL=http://127.0.0.1:18001 uv run pytest tests/test_integration_powercontext.py
```

seekdb 集成测试会创建并删除 `cd_it_<随机后缀>` 数据库；不要把真实数据库名配给它。
