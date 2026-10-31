# 运行手册

面向部署与日常操作。快速上手见 [README](../README.md)，架构与数据模型见 [architecture.md](architecture.md)。

## 1. 环境与端口

| 项 | 要求 | 本项目验证值 |
| --- | --- | --- |
| OS | Windows 10/11 或 Linux | Windows 10.0.26300 |
| Docker | Docker Engine / Desktop + Compose v2.17+ | Docker Desktop，Compose v5.5.1 |
| Python | >= 3.11 | 3.12 |
| Node.js | >= 20.19 或 >= 22.12（仅构建 Web） | 24.x |
| 内存 | 建议 >= 4 GB 可用 | seekdb 容器限制 2 GB |
| 磁盘 | 镜像与数据约 2 GB，模型约 86 MB | 见 `docker system df` |

默认端口（均只绑定本机回环）：

- seekdb：`127.0.0.1:2881`（MySQL 协议）
- PowerContext：`127.0.0.1:8000`（HTTP）
- Web：`127.0.0.1:8787`（FastAPI，同时提供 API 与 `web/dist`）

端口被占用时改 `.env` 中 `YINJU_SEEKDB_PORT` / `YINJU_POWERCONTEXT_PORT` / `YINJU_WEB_PORT`，应用与 compose 读同一组变量。

## 2. 配置

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

关键变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `YINJU_SEEKDB_HOST/PORT/USER/PASSWORD/DATABASE` | `127.0.0.1:2881` / root / 空 / `yinju` | 证据库连接 |
| `YINJU_POWERCONTEXT_HOST/PORT/TOKEN` | `127.0.0.1:8000` / 空 | 记忆服务；仅开启鉴权时需要 token |
| `YINJU_MEMORY_ENABLED` | `true` | 核对后写入记忆；`audit --no-memory` 单次关闭 |
| `YINJU_EMBEDDING_PROVIDER` | `local` | 本地 ONNX；当前只实现 local |
| `YINJU_VERIFIER_PROVIDER` | `none` | `none` 为无 key 基线；`openai` / `anthropic` 需模型与 key |
| `YINJU_VERIFIER_MODEL` | 空 | LLM 判定模型名 |
| `YINJU_DATA_DIR` | `data` | 草稿、报告、缓存与上传的根目录 |
| `YINJU_WEB_HOST/PORT` | `127.0.0.1:8787` | Web 工作台 |
| `YINJU_WEB_DIR` | `web/dist` | 前端构建产物目录 |

`.env` 已被 `.gitignore` 忽略；密钥只写入本地 `.env`。

## 3. 服务管理

```bash
docker compose up -d --build --wait   # 构建并启动，等待 healthy
docker compose ps                     # 两个服务应为 healthy
docker compose logs -f seekdb         # 查看日志
docker compose down                   # 停止（保留数据卷）
docker compose down -v                # 停止并删除数据卷
```

期望容器：

- `yinju-seekdb-1`：`healthy`，镜像固定为 `quay.io/oceanbase/seekdb@sha256:4db49618…`
- `yinju-powercontext-1`：`healthy`，镜像由 `deploy/powercontext/Dockerfile` 构建

PowerContext 镜像构建固定 `powercontext[cli,server]==1.4.0`，默认使用清华 PyPI 镜像；网络不通时覆盖：

```bash
docker compose build --build-arg PIP_INDEX_URL=https://pypi.org/simple powercontext
```

本机已有 `powercontext-server:1.4.0` 时可跳过构建：

```bash
docker tag powercontext-server:1.4.0 yinju-powercontext:1.4.0
docker compose up -d --no-build --wait
```

seekdb 无法按 digest 拉取时，可临时把 `docker-compose.yml` 的 `image` 改为 `quay.io/oceanbase/seekdb:latest`，并用 `SELECT version()` 确认仍为 `seekdb-v1.4.0.0`。

## 4. 安装与自检

```bash
uv sync --extra dev
uv run yinju doctor
```

不使用 uv：

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"    # Windows
.venv/bin/pip install -e ".[dev]"        # Linux / macOS
```

`doctor` 检查四项：`data` 可写、seekdb 可达与版本、PowerContext 就绪、模型配置。任一失败返回非零退出码并给出 hint。首次入库前 `database=yinju missing` 属正常。

单测与静态检查：

```bash
uv run pytest
uv run ruff check .
```

seekdb 集成测试默认跳过，显式开启（会创建并删除临时数据库 `yinju_it_<随机后缀>`）：

```bash
YINJU_TEST_SEEKDB=1 YINJU_SEEKDB_PORT=2881 uv run pytest \
  tests/test_integration_seekdb.py tests/test_integration_audit.py
```

PowerContext 集成测试会向真实服务写入随机项目，建议指向可丢弃实例：

```bash
YINJU_TEST_POWERCONTEXT_URL=http://127.0.0.1:18001 uv run pytest \
  tests/test_integration_powercontext.py
```

## 5. 入库

### 5.1 输入约定

`bib.json` 的键必须匹配 `[A-Za-z0-9_:-]+`，值可以是相对 PDF 路径，或带元数据的对象：

```json
{
  "vaswani2017": {
    "file": "papers/1706.03762.pdf",
    "title": "Attention Is All You Need",
    "authors": "Ashish Vaswani et al.",
    "year": 2017,
    "source_url": "https://arxiv.org/abs/1706.03762"
  }
}
```

PDF 路径相对 `bib.json` 所在目录。样例在 `data/samples/bib.json`；Web 上传的 PDF 写入 `data/uploads/` 与独立的 `data/uploads/bib.json`，不改动样例书目。

### 5.2 证据单元

- 段级 `para`：页内连续句子组成，单块不超过 750 字符；
- 句级 `sent`：不少于 20 字符，`parent_id` 指向所在段；
- ID：`{paper_key}:p{page}:para{n}` / `{paper_key}:p{page}:sent{n}`，页码从 1 开始；
- 文本先去连字符换行、合并空白；不识别章节，不做 OCR，扫描版 PDF 明确报错。

### 5.3 命令与计数

```bash
uv run yinju ingest --bib data/samples/bib.json
uv run yinju ingest --bib data/samples/bib.json --force   # 忽略已入库标记，重建
uv run yinju ingest --key devlin2019                      # 只处理单篇
uv run yinju papers                                       # 论文与单元计数
uv run yinju papers --json
```

计数口径：

- `embedded`：本次未命中缓存、需要嵌入的单元数；
- `computed`：按文本去重后真正计算的唯一向量数；
- `cached`：直接命中本地缓存的单元数；
- `embedded + cached = 单元总数`。

embedding 缓存位于 `data/runtime/embedding_cache.sqlite3`，按「模型标识 + 文本 SHA-256」存 float32 向量。首次入库还需下载 all-MiniLM-L6-v2（约 86 MB），缓存后不再下载。

## 6. 检索

```bash
uv run yinju search "The Transformer follows this overall architecture" \
  --paper-key vaswani2017 --unit-type sent --limit 3
```

`--mode hybrid`（默认）：

- 全文检索：从查询抽取英文关键词，用 `$contains` 或 `$or` 过滤；
- 向量检索：本地 embedding；
- **两路都带 `paper_key` 与 `unit_type` 过滤**，不会返回其他论文的证据；
- 融合在应用侧完成：`sum(1 / (60 + rank))`，同分按 `unit_id` 排序；报告里保留两路各自排名。

`--mode vector` 为纯向量检索。中文查询抽不到英文关键词时全文检索自动跳过，只剩限定论文内的向量检索；`search` 只检索、不判定。

## 7. 核对

### 7.1 草稿约定

Markdown 中引用写成 `[@key]`，一条主张可带多根引用 `[@key1; @key2]`：

```markdown
The Transformer relies entirely on attention mechanisms and dispenses with
recurrence and convolutions [@vaswani2017].
```

- 空行、标题、列表项、引用块类型变化会切开主张；标题行与围栏代码块不参与解析；
- 每个含 `[@...]` 的块生成一条主张（`claim-01` 起），引用去重；
- 只接受 `[@key]` / `[@a; @b]`，带定位符的写法（如 `[@key p3]`）报错；
- 去掉引用后不足 10 字符、或整篇没有引用，报错；
- 草稿中的键必须在 `bib.json` 中存在，且论文已入库，否则预检阶段退出。

### 7.2 执行

```bash
uv run yinju audit \
  --draft data/samples/draft.md \
  --bib data/samples/bib.json \
  --out data/runtime/reports
```

流程：解析草稿 → 校验 bib 与论文注册表 → 每条主张段落级混合检索（默认前 5 段）→ 段内选句（`0.60 × 余弦 + 0.35 × 关键词覆盖`，数字一致性微调，取前 8 条）→ 判定 → 写报告 → 同步记忆。

同一主张的多条引用取**最差**结论；单条引用失败只标记该条 `unknown`，整体仍产出报告。

### 7.3 无 key 基线

`YINJU_VERIFIER_PROVIDER=none` 时：

- 带单位数字与原文冲突 → `unsupported`；
- 余弦与覆盖都低于 0.35 → `unsupported`；
- 主张含数字但最佳证据缺失，且余弦低于 0.55 → `unsupported`；
- 高相关（余弦 >= 0.62 且覆盖 >= 65%，或数字命中、余弦 >= 0.70 且覆盖 >= 45%）→ `partial`（high）；
- 中等相关 → `partial`（medium）；其余 → `unknown`；
- **基线永远不出具 `supported`**，报告首屏与 JSON 均带提示。

配置 LLM 判定器需同时设置 `YINJU_VERIFIER_PROVIDER`、`YINJU_VERIFIER_MODEL` 与对应 key；模型必须返回严格 JSON，且 `evidence_id` 必须来自候选集合。

## 8. 报告与记忆

报告目录（CLI 与 Web 共用）：

```text
data/runtime/reports/<run_id>-<草稿名>/
├── report.md      # 汇总、逐条结论、原句、页码、段落 RRF 表、句候选表
├── report.csv     # UTF-8-SIG，一条引用一行
├── report.json    # 完整结构化结果，供 Web 与审计视图消费
└── memory.json    # 仅 Web 任务写入：记忆同步摘要（CLI 在终端输出摘要）
```

CLI 输出 `claims/citations | supported/partial/unsupported/unknown | review/errors` 三组计数与文件路径，最后一行 `memory: project=... scope=... written=... skipped=... handoff=rN` 为记忆同步摘要；`--json` 时报告与 `memory` 一起打到 stdout、摘要改到 stderr。任一条出错退出码为 1，报告仍落盘。

记忆同步（默认开启）：

- Scope 为 `yj:{bib 相对 data/ 的路径去后缀}`，如 `yj:samples/bib`；
- 写入 3 条核对标准、1 条范围约束（按 `(kind, text)` 去重）、每条主张一条 `decision`、一条运行摘要、每个待复核项一条 `next_step`；
- Handoff 用本地确定性草稿提交，不调用 `/v1/handoff/prepare`，不消耗模型额度；相同草稿重复提交幂等；
- CLI 成功输出 `memory: project=... scope=... written=... skipped=... handoff=rN`；
- PowerContext 不可用时只写 stderr，报告退出码不受影响。

## 9. Web 与 API

```bash
npm --prefix web install
npm --prefix web run build
uv run yinju serve                 # 127.0.0.1:8787
uv run yinju serve --port 8788
```

未构建时首页返回 404 JSON，并提示构建命令。页面为 hash 路由，静态托管无需服务端改路由。

- **核对台** `#/`：选择草稿与论文库、预览引用、提交任务、轮询进度；
- **示例** `#/audit/demo`：自动载入 `data/samples/photon-demo.md` 并运行；
- **论文库** `#/papers`：论文与单元计数、PDF 上传（<= 25 MB，校验 `%PDF-` 魔数与内容哈希）；
- **报告** `#/reports`：列表、详情、md / csv / json 下载；
- **项目记忆** `#/memory`：交接卡、继续上次核对、四类条目筛选与显式写入；
- **系统状态** `#/system`：模型与判定器配置、记忆开关、seekdb / PowerContext 自检、最近任务、API 文档。

接口：

```text
GET  /api/config | /api/health | /api/papers | /api/drafts | /api/bibliographies
GET  /api/reports | /api/reports/{run_id} | /api/reports/{run_id}/download/{kind}
GET  /api/jobs | /api/jobs/{id}
GET  /api/memory/projects | /api/memory | /api/memory/search
POST /api/audits | /api/uploads | /api/memory/entries | /api/memory/handoff/continue
GET  /api/docs（OpenAPI）
```

- 核对与上传返回 `202` 与任务快照，后台线程执行；前端每 700 ms 轮询；同类任务并发提交返回 `409`。
- 任务队列在进程内存中，重启后历史任务不保留，报告仍在磁盘。
- 上传接口为 `POST /api/uploads?filename=&title=&authors=&year=`，请求体为原始 PDF 字节；非 PDF / 空文件 / 超过 25 MB 分别返回 `415 / 400 / 413`。
- 路径边界：草稿与书目必须在 `data/` 内；报告目录名只接受 `[A-Za-z0-9_.-]`；API 与页面同源，默认只绑回环地址。

## 10. 标注集评测

`data/samples/labels.json` 为人工标注集，每条包含 `id`、`claim`、`citation`、`label`、`evidence_pages`、`evidence_units`、`source`、`notes`。

```bash
uv run yinju eval --labels data/samples/labels.json --bib data/samples/bib.json
uv run yinju eval --labels data/samples/labels.json --bib data/samples/bib.json \
  --out data/runtime/eval --json
```

评测复用核对链路，逐条复算并写出 `data/runtime/eval/<dataset>.md|json`，不写 PowerContext，默认不调用 LLM。

指标：

- **严格准确率**：四档与人工标注完全一致的比例；
- **不支持召回 / 精确率 / F1**：针对人工标为无支持的条目；
- **无支持自动放行**：人工标为无支持却判 `supported` 的条数（最危险）；
- **无支持处理率**：判 `unsupported` 或进入复核的比例；
- **复核率**、**证据页命中率**、平均单条耗时、错误数。

## 11. 故障排查

| 现象 | 处理 |
| --- | --- |
| `bind: address already in use` | 改 `.env` 端口；`netstat -ano \| findstr :8000` 查占用 |
| seekdb 容器启动即退出 | 不要用 Windows 目录 bind mount 挂 `/var/lib/seekdb`，compose 已用命名卷；看 `docker logs yinju-seekdb-1` |
| PowerContext 返回 401/403 | 默认关闭鉴权且只绑回环；若改过访问模式，在 `.env` 配 `YINJU_POWERCONTEXT_TOKEN` |
| PowerContext `health/ready` 长时间不通过 | 首次启动需初始化 SQLite，通常 20 s 内就绪；看 `docker logs yinju-powercontext-1` |
| Git Bash 下容器路径报 `Permission denied: '/D:'` | MSYS 路径转换所致；加 `MSYS_NO_PATHCONV=1` 或改用 PowerShell |
| 记忆 API 返回 `memory writes are disabled` | 检查 `YINJU_MEMORY_ENABLED`，它在进程启动时读取，改完需重启 `yinju serve` |
| 核对成功但报告显示记忆未写入 | PowerContext 不可达或写入失败；报告不受影响，按 hint 检查容器与端口 |
| 重跑后记忆条数增加、Handoff 版本递增 | 标准与约束按文本去重；判断与下一步按 `run_id` 追加，属预期 |
| 相同报告重复提交但版本不变 | PowerContext 对相同 Handoff 草稿幂等 |
| `seekdb unavailable` | `docker compose up -d seekdb` 后重跑 `yinju doctor`，确认端口一致 |
| 首次 embedding 很慢 | CPU 嵌入约 5–10 单元/秒；模型约 86 MB 缓存在 `~/.cache/pyseekdb`，之后增量入库约 2 秒，`--force` 全命中缓存约 19 秒 |
| `no extractable text` | PDF 无可提取文本（扫描件）；本项目不做 OCR |
| `invalid paper key` / `PDF not found` | 按 §5.1 检查键字符与相对路径 |
| `embedding provider ... not implemented` | 当前只实现本地 ONNX，设 `YINJU_EMBEDDING_PROVIDER=local` |
| `doctor` 说 `database missing` | 首次 ingest 自动建库；持续缺失时检查 seekdb 账号权限 |
| `no claims with [@key] citations found` | 草稿没有可解析引用；检查 `[@key]` 写法 |
| `draft cites keys missing from bibliography` | 把缺失键补进 `--bib` 指向的 JSON |
| `papers not ingested: ...` | 被引论文未入库；按提示执行 `yinju ingest --key ...` |
| 基线全是 `partial`/`unsupported` | `verifier=none` 的设计如此，`supported` 需配置 LLM 判定器 |
| `labels cite keys missing from bibliography` | 标注集的 `citation` 没写进 `bib.json` |
| `evidence_units require evidence_pages` | 标注条目给了证据单元却没给证据页；补 `evidence_pages` 或两者都留空 |
| 首页返回 `frontend is not built` | 先 `npm --prefix web install && npm --prefix web run build` |
| 提交核对返回 `409` | 已有同类任务在跑；等待结束或重启服务清空内存队列 |
| 提交核对返回 `400` | 草稿/书目不在 `data/`、后缀不符或文件不存在；改用页面下拉选择 |
| 页面仍显示旧版本 | `web/dist` 是构建产物；重新构建后刷新 |

## 12. 数据清理

```bash
# 只清运行产物，保留 Docker 卷
rm -rf data/runtime data/uploads

# 同时清空 seekdb 证据库与 PowerContext 记忆
docker compose down -v
rm -rf data/runtime data/uploads
```

删除后需重新执行 `yinju ingest`（向量缓存也一并清除，需重新计算）。
