# 引据 CitationProof

> 每一句引用，都能落回原文；每一次判断，都不用重做。

引据是一个面向研究生与科研人员的「主张 → 原文证据 → 引用核对」工作台。导入论文与 Markdown 草稿后，它**只在该条引用对应的论文内部**检索证据，输出「支持 / 部分支持 / 不支持 / 无法判断 + 原文原句 + 页码」，并把核对标准、已确认判断与进度写入 PowerContext，下一次会话或换人接手可以直接继续。

程序设计思维课程设计项目。当前仓库是可运行版本：固定管线 + Web 工作台 + seekdb 证据库 + PowerContext 研究记忆；面向标准 Agent 的目标架构见 [docs/architecture.md](docs/architecture.md)。

## 它解决什么

1. 引用并不支持主张：过度转述、断章取义；
2. 引用错配：把 A 论文的数据写成 B 论文的引用；
3. 30 条引用逐条翻 PDF，人工约 2 小时；
4. 同一篇论文被不同章节、不同人反复核对，判断不留痕。

关键设计：**检索必须限定在被引论文内**。不限论文时，一条错误归属的主张会从另一篇论文召回到「看起来很像」的证据，这正是要避免的假支持。

## 技术分工

| 组件 | 在项目中的作用 |
| --- | --- |
| seekdb 1.4.0.0 | 证据库：证据单元（句/段 + 页码）的向量 + IK 全文混合检索，按论文/页码过滤；论文注册表 |
| PowerContext 1.4.0 | 研究记忆：项目 Scope、核对标准、已确认/推翻的判断、约束、进度 Handoff |
| FastAPI | 同源提供 `/api/*` 与 `web/dist` 静态页面；核对与入库为后台任务 |
| React 19 + Vite 8 | Web 工作台：核对台、论文库、报告、项目记忆、系统状态 |
| PyMuPDF + pyseekdb | PDF 分页解析与本地 ONNX 向量（all-MiniLM-L6-v2，384 维） |

文档正文与记忆分开：PowerContext 只存「判断与进度」，不存论文正文；语义召回由 seekdb 承担。PowerContext 未配置生成模型时记忆检索走全文（`mode: "text"`）。

## 目录结构

```text
.
├── README.md
├── docker-compose.yml          # seekdb + PowerContext
├── .env.example                # 配置模板（复制为 .env）
├── pyproject.toml / uv.lock    # Python 依赖（包名 yinju）
├── deploy/powercontext/        # PowerContext 1.4.0 镜像构建
├── src/yinju/                  # FastAPI、入库、检索、判定、报告、记忆
├── tests/                      # pytest（含默认跳过的集成测试）
├── web/                        # React + Vite 工作台
├── data/samples/               # 3 篇样例 PDF、草稿、标注集
└── docs/                       # 架构说明、运行手册
```

## 部署与运行

以下步骤在一台干净机器上从零到可访问 Web 工作台。默认端口 `2881`（seekdb）、`8000`（PowerContext）、`8787`（Web），全部只绑定本机回环地址。

### 0. 环境要求

| 项 | 要求 |
| --- | --- |
| Docker | Docker Desktop 或 Docker Engine，Compose v2.17+ |
| Python | >= 3.11（本项目验证 3.12） |
| Node.js | >= 20.19 或 >= 22.12（仅构建 Web） |
| 内存 / 磁盘 | 建议可用内存 >= 4 GB；镜像与数据约 2 GB，embedding 模型约 86 MB |
| 网络 | 首次拉取 seekdb 镜像、构建 PowerContext、下载 embedding 模型 |

### 1. 获取代码并配置

```bash
git clone https://github.com/simpur-dev/course-design.git
cd course-design
cp .env.example .env            # Windows: copy .env.example .env
```

默认配置即可启动。端口被占用时改 `.env`，应用与 compose 读同一组变量，不需要改两处：

```dotenv
YINJU_SEEKDB_PORT=2884
YINJU_POWERCONTEXT_PORT=18000
YINJU_WEB_PORT=8788
```

### 2. 启动 seekdb 与 PowerContext

```bash
docker compose up -d --build --wait
docker compose ps
```

期望两个服务都是 `healthy`。首次执行会拉取固定 digest 的 seekdb 镜像，并按 `deploy/powercontext/Dockerfile` 构建 PowerContext 1.4.0。

构建或拉取失败时的两条退路：

```bash
# 1) PyPI 镜像不可用：改用官方源重新构建
docker compose build --build-arg PIP_INDEX_URL=https://pypi.org/simple powercontext

# 2) seekdb 无法按 digest 拉取：把 docker-compose.yml 中的 image 临时改为
#    quay.io/oceanbase/seekdb:latest，版本应仍为 seekdb v1.4.0.0
```

手动健康检查：

```bash
docker compose exec seekdb mysqladmin ping -h127.0.0.1 -P2881 -uroot -s
curl http://127.0.0.1:8000/health/ready   # 端口随 .env 的 YINJU_POWERCONTEXT_PORT
```

### 3. 安装应用并自检

```bash
uv sync --extra dev
uv run yinju doctor
```

不使用 uv 时：

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"      # Windows
.venv/bin/pip install -e ".[dev]"          # Linux / macOS
.venv/Scripts/yinju doctor                 # Windows
.venv/bin/yinju doctor                     # Linux / macOS
```

期望输出（端口与库名随 `.env` 变化）：

```text
[OK  ] data          .../course-design/data (writable)
[OK  ] seekdb        5.7.25-OceanBase seekdb-v1.4.0.0; database=yinju missing (created on first ingest)
[OK  ] powercontext  v1.4.0 ready at http://127.0.0.1:8000
[OK  ] providers     embedding=local verifier=none (model downloads on first ingest)
```

`database=... missing` 在首次入库前是正常的，数据库由 `yinju ingest` 自动创建。

### 4. 导入样例论文

```bash
uv run yinju ingest --bib data/samples/bib.json
uv run yinju papers
```

三篇样例：Transformer（382 单元）、BERT（592 单元）、Photon SIGMOD'22（791 单元）。首次入库会下载 all-MiniLM-L6-v2（约 86 MB）并在 CPU 上计算向量，本机实测约 3 分钟；之后增量入库约 2 秒，`--force` 全量重建命中缓存约 19 秒。

### 5. 运行一次核对

```bash
uv run yinju audit \
  --draft data/samples/photon-demo.md \
  --bib data/samples/bib.json \
  --out data/runtime/reports
```

无 key 基线的预期结果：5 条主张中 4 条 `partial`、1 条 `unsupported`（第 5 条故意把 100 TB 写成 500 TB），需复核 4 条，错误 0。产物在 `data/runtime/reports/<run_id>-photon-demo/`：

```text
report.md / report.csv / report.json     # 结论、原句、页码、检索排名
```

命令最后一行 `memory: project=... scope=... written=... skipped=... handoff=rN` 是 PowerContext 同步摘要；通过 Web 运行时同内容会额外写成 `memory.json`。

也可用 `data/samples/draft.md` 跑 4 条主张的 NLP 样例（3 `partial` + 1 `unsupported`）。

### 6. 启动 Web 工作台

```bash
npm --prefix web install
npm --prefix web run build
uv run yinju serve
```

打开 <http://127.0.0.1:8787>（端口被占用时用 `uv run yinju serve --port 8788` 或改 `YINJU_WEB_PORT`）。页面为 hash 路由：

| 路由 | 内容 |
| --- | --- |
| `#/` | 核对台：选草稿/论文库、提交任务、查看进度与结论 |
| `#/audit/demo` | 内置 Photon 示例，自动运行 |
| `#/papers` | 论文库：论文与证据单元计数、PDF 上传（<= 25 MB） |
| `#/reports` | 报告列表与三种格式下载 |
| `#/memory` | 项目记忆：标准/判断/进度、召回测试、继续上次核对 |
| `#/system` | 服务状态、模型配置、API 文档入口 |

## 验证清单

按顺序执行，全部符合即部署成功：

- [ ] `docker compose ps` 中 `yinju-seekdb-1` 与 `yinju-powercontext-1` 均为 `healthy`
- [ ] `uv run yinju doctor` 输出 4 行 `[OK]`
- [ ] `uv run yinju papers` 列出 3 篇论文，`UNITS` 合计 1765
- [ ] 核对命令输出 4 `partial` + 1 `unsupported`，报告目录含 3 个文件
- [ ] 命令末尾 `memory:` 摘要显示 `written` 大于 0（PowerContext 可用时）
- [ ] 浏览器打开 `#/memory` 能看到本次写入的判断与「继续上次核对」
- [ ] 浏览器打开 `#/reports` 能下载 md / csv / json

## 配置项

完整模板见 [.env.example](.env.example)。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `YINJU_SEEKDB_HOST/PORT` | `127.0.0.1:2881` | seekdb 地址，同时决定 compose 端口映射 |
| `YINJU_SEEKDB_PASSWORD` | 空 | seekdb 仅本机开发使用，勿暴露公网 |
| `YINJU_POWERCONTEXT_HOST/PORT` | `127.0.0.1:8000` | PowerContext 地址 |
| `YINJU_MEMORY_ENABLED` | `true` | 核对后写入项目记忆；`audit --no-memory` 可单次关闭 |
| `YINJU_EMBEDDING_PROVIDER` | `local` | 本地 ONNX 向量，无需 key |
| `YINJU_VERIFIER_PROVIDER` | `none` | 无 key 基线；`openai` / `anthropic` 需同时配置模型与 key |
| `YINJU_WEB_HOST/PORT` | `127.0.0.1:8787` | Web 工作台监听地址 |

密钥只写进 `.env`，`.env` 已被 `.gitignore` 忽略。

## 常用命令

```bash
uv run yinju doctor                                  # 自检
uv run yinju ingest --bib data/samples/bib.json      # 入库（增量）
uv run yinju ingest --bib data/samples/bib.json --force
uv run yinju papers                                  # 论文与单元计数
uv run yinju search "The Transformer follows this overall architecture" \
  --paper-key vaswani2017 --unit-type sent --limit 3
uv run yinju audit --draft data/samples/draft.md \
  --bib data/samples/bib.json --out data/runtime/reports
uv run yinju eval --labels data/samples/labels.json --bib data/samples/bib.json
uv run yinju serve
uv run pytest                                        # 单测；seekdb/PowerContext 集成测试默认跳过
uv run ruff check .
```

集成测试需要真实服务：

```bash
YINJU_TEST_SEEKDB=1 uv run pytest tests/test_integration_seekdb.py tests/test_integration_audit.py
YINJU_TEST_POWERCONTEXT_URL=http://127.0.0.1:18001 uv run pytest tests/test_integration_powercontext.py
```

## 数据与产物

| 路径 | 内容 |
| --- | --- |
| `data/samples/` | 随仓库提供的样例 PDF、草稿、标注集 |
| `data/uploads/` | Web 上传的 PDF 与书目（运行时生成，已忽略） |
| `data/runtime/reports/` | 核对报告 md / csv / json（Web 运行另含 `memory.json`） |
| `data/runtime/embedding_cache.sqlite3` | 按模型 + 文本哈希缓存的向量 |
| `data/runtime/eval/` | 标注集评测输出 |

seekdb 与 PowerContext 的数据在 Docker 命名卷 `seekdb-data`、`powercontext-data` 中。重置数据：

```bash
docker compose down -v          # 删除两个命名卷（同时清空证据库与记忆）
rm -rf data/runtime data/uploads
```

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `bind: address already in use` | 端口被占用，改 `.env` 中三个 `PORT` 变量后重新 `docker compose up -d --wait` |
| seekdb 镜像拉取失败 | 按上文改为 `quay.io/oceanbase/seekdb:latest`，确认版本仍为 `seekdb-v1.4.0.0` |
| PowerContext 构建失败 | 切换 `PIP_INDEX_URL` 重新构建；或复用本机已有 `powercontext-server:1.4.0` 镜像 |
| embedding 模型下载失败 | 默认使用 `hf-mirror.com`；可显式设置 `HF_ENDPOINT=https://hf-mirror.com` 后重试 |
| `doctor` 报 seekdb 不可达 | 先 `docker compose up -d seekdb`，确认 `.env` 端口与 `docker compose ps` 一致 |
| 记忆未写入但核对成功 | PowerContext 不可达时属预期；CLI 摘要会带错误，Web 报告的 `memory.json` 带错误与 hint |
| 首页返回 `frontend is not built` | 先执行 `npm --prefix web install && npm --prefix web run build` |

更多故障排查见 [docs/runbook.md](docs/runbook.md#11-故障排查)。

## 文档

- [docs/architecture.md](docs/architecture.md)：当前实现架构、数据模型、目标架构
- [docs/runbook.md](docs/runbook.md)：配置、入库/检索/判定口径、Web 与 API、评测、故障排查
- [web/README.md](web/README.md)：前端结构与路由

## 已知限制

- **无 key 基线不出具「支持」**：`verifier=none` 只输出 `partial` / `unsupported` / `unknown` 并提示复核；要得到 `supported` 需配置 LLM 判定器。
- 只处理文本型 PDF，不做 OCR、图表理解与双栏章节识别。
- 任务队列在进程内存中，重启后历史任务不保留（报告仍在磁盘上）。
- 单用户、本机回环部署，没有登录与权限体系。
- 中文主张抽不到英文关键词时，全文检索自动跳过，只剩限定论文内的向量检索。
- 目标架构中的 Agent 内核、监督对话、断点恢复尚未实现，见 [docs/architecture.md](docs/architecture.md)。

## 第三方与许可

样例论文与第三方软件的来源、许可说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。样例 PDF 仅作本地测试输入，不再分发其衍生内容。
