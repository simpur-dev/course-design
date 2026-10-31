# 三人分工与协作规则

基线是 2026-10-31 重构后的仓库：`backend/` + `frontend/`，现有固定管线功能完整、测试全绿。三人直接在 `main` 的后续提交上并行推进目标架构 v5，不再另起一套骨架。

## 1. 目标与边界

课程设计目标：把固定管线升级为**单执行 Agent**，增加风险分诊、有界 ReAct、双证据通道、监督对话与断点恢复。

明确不做：

- 不做多 Agent 角色扮演；执行 Agent 始终只有一个。
- 监督对话层只观察和控制，不写结论、不改证据。
- 不引入第二套后端框架或前端 UI 库；扩展走现有注册表与协议。

## 2. 所有权

| 成员 | 角色 | 拥有的目录/文件 | 核心交付 |
| --- | --- | --- | --- |
| A | 执行 Agent 与判定 | `backend/agent/`、`backend/audit/`、`tests/test_audit*.py`、`tests/test_verdicts.py`、`tests/test_evaluation.py`、`tests/test_claims.py`、`tests/test_report.py`、`tests/test_terms.py` | 风险分诊、策略选择、有界取证循环、复核闸门、结论装配；判定器协议与报告契约 |
| B | 证据与运行平台 | `backend/evidence/`、`backend/runtime/`、`backend/diagnostics/`、`deploy/`、`docker-compose.yml`、`tests/test_ingest.py`、`tests/test_store_hybrid.py`、`tests/test_embeddings.py`、`tests/test_bibliography.py`、`tests/test_units.py`、`tests/test_doctor.py`、`tests/test_integration_*.py` | 入库与检索质量、运行状态与恢复层（checkpoint / 事件日志 / 状态机）、工具运行环境、OA 获取层 |
| C | 接口、记忆与前端 | `backend/api/`、`backend/cli/`、`backend/memory/`、`frontend/`、`tests/test_api.py`、`tests/test_cli.py`、`tests/test_memory.py`、`tests/test_powercontext.py` | HTTP/CLI 契约、项目记忆与 Handoff、监督对话 API、前端运行控制台与页面 |
| 共享 | — | `backend/core/config.py`、`pyproject.toml`、`.env.example`、`.github/`、`README.md`、`docs/architecture.md`、`docs/interfaces.md`、`docs/runbook.md` | 改动需在群里说明，并由至少一人复核 |

说明：

- **A 不直接改 `api`/`frontend`**：Agent 新能力先以 `AuditAgent` / 服务函数暴露，由 C 接到接口与页面。
- **B 不直接改报告 JSON**：检索与 checkpoint 的新增信息通过 data class 字段提供，报告序列化由 A 维护。
- **C 不写核对结论**：监督对话只消费 RunState 与已有 `step/evidence_id`，不生成判定。
- 跨目录 bug 由对应 owner 修；紧急修复需在提交说明中写明原因并通知 owner。

## 3. 已冻结的契约

以下契约在 v5 期间**只允许向后兼容的增字段**；破坏性修改必须三人同意并同步文档与测试。

1. **报告 JSON**：`report.json` 顶层字段与 `summary` 计数（见 `docs/interfaces.md` 2.3）。
2. **核对入口**：`run_audit(settings, RunSpec, progress) -> dict` 与 `AuditAgent.run` 的签名。
3. **任务模型**：`Job` 字段与 `queued/running/succeeded/failed` 状态机；`JobManager` 单任务互斥语义。
4. **HTTP**：现有 `/api/*` 路径、状态码与 `{detail:{message,hint}}` 错误体；新增接口只追加。
5. **前端路由**：`RouteState` 判别联合与 `resolveRoute` 注册表；页面通过 `shared/api` 访问后端。
6. **记忆 Scope**：`cd:{project}`；四类 kind 与 Handoff 的 `untrusted_history` 语义。
7. **技术标识**：`backend` 包、`citationproof` CLI、`APP_` 环境变量、`course_design` 默认库、`frontend/`。不要再引入旧包名或旧前缀。

## 4. 并行开发规则

### 4.1 分支与提交

- 分支：`feat/a-<topic>`、`feat/b-<topic>`、`feat/c-<topic>`；合并前先 rebase 到最新 `main`。
- 提交使用 Conventional Commits：`feat(agent): ...`、`fix(retrieval): ...`、`docs(interfaces): ...`、`test(api): ...`。
- 一个提交只解决一件事；不提交 `.env`、`data/runtime/`、`data/uploads/`、`frontend/dist/`。

### 4.2 接口变更流程

1. 先改 `docs/interfaces.md` 的对应小节（或提出 diff）。
2. 在群里给出「字段/签名前后对比 + 影响目录」。
3. 受影响 owner 确认后，先加兼容字段/默认值，再改调用方。
4. 同步测试与前端类型，最后删除旧路径。

### 4.3 每日集成

每天至少一次：

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
npm --prefix frontend run lint
npm --prefix frontend run build
```

合并到 `main` 前必须全绿；CI 与本地命令一致。涉及外部服务的改动，再跑一次真实链路：

```bash
docker compose up -d --wait
uv run citationproof doctor
uv run citationproof ingest --bib data/samples/bib.json
uv run citationproof audit --draft data/samples/draft.md --bib data/samples/bib.json --out data/runtime/reports
```

## 5. v5 里程碑与各自任务

### M0 基线（已完成）

- 后端按 `core/evidence/audit/memory/runtime/agent/api/cli/diagnostics` 分层，`api`/`cli` 只做适配。
- 前端按 `app/shared/features` 分层，路由注册表与 `shared/api` 稳定。
- 原有页面、任务、报告、上传、记忆与 CLI 功能保持；测试与构建通过。

### M1 单 Agent 内核

**A**

- 在 `AuditAgent` 内加入 `triage(claim, citations)`：数字核对 / 归属溯源 / 定义定位 / 混合检索 / 外部锚定。
- 定义 `Step` 与 `RunState`（只追加），把现有一次检索升级为预算内的多步取证；每步产出可引用的 `step_id` 与 `evidence_id`。
- 复核闸门：`needs_review` 由风险与证据强度共同决定，保留四档判定口径。
- 工具注册表：取证、获取登记、外部记录查询统一 JSON Schema；只读/写入分权。
- 测试覆盖：策略选择、预算耗尽、证据不足、判定器返回非法 evidence_id。

**B**

- 新增 `RunCheckpoint` 与只追加事件日志（建议落在 `backend/runtime/`），定义状态机与恢复前置条件（输入哈希、版本）。
- 实现协作式暂停/恢复的步边界语义；提供 checkpoint 读写接口，不接管报告。
- 检索侧支持按论文过滤的检索质量评估集，给 A 的策略提供稳定输入。

**C**

- 监督对话只读 API：查询 RunState、步骤、证据与预算；控制 API：暂停/恢复/取消。
- 前端新增运行控制台：步骤时间线、证据抽屉、暂停/恢复按钮；答案展示必须带 `step_id`/`evidence_id`。
- 保持现有核对台可用；新增轮询只读接口，不改变既有 job 协议。

### M2 恢复与监督闭环

**A**：把 Agent 步骤写入 RunState，恢复时从 checkpoint 继续而不是重跑已完成步骤；补齐失败重试与幂等。

**B**：checkpoint 持久化、事件日志回放、输入哈希校验与损坏恢复；压测并发与中断场景。

**C**：断点恢复入口、状态机可视化、错误码与 hint 展示；补 API/前端测试。

### M3 外部证据通道与 OA

**B**：标识解析、开放获取源优先级、下载守卫、缓存登记；失败如实返回，不绕付费墙。

**A**：外部记录只做锚定/反驳，不能升级为「已支持」；在报告中标注通道来源。

**C**：在报告与记忆页展示外部记录标记；接口保持主通道判定不变。

## 6. 验收标准

每个里程碑共同满足：

1. **功能不回退**：现有核对、入库、报告下载、上传、记忆、系统状态页面可用；样例结果数量与判定档位不劣化。
2. **接口有文档**：新增/变更的公共签名、JSON 字段、错误码已写入 `docs/interfaces.md`。
3. **测试有失败路径**：新增能力至少覆盖一个错误/预算耗尽场景；不只测 happy path。
4. **全绿门禁**：`ruff`、`pytest`、前端 `lint`、`build` 全部通过；CI 不得靠跳过测试变绿。
5. **真实链路**：涉及 Agent/检索/记忆的里程碑，必须用真实 seekdb + PowerContext 跑一次 `doctor → ingest → audit → Web`。
6. **可继续性**：交接时在 PR 描述中写清「已实现 / 未实现 / 下一步入口」，不留下无法运行的半成品。

## 7. 协作检查表

- [ ] 我的改动只在已分配目录内（共享文件已通知）。
- [ ] 新公共名字已出现在包根 `__all__` 或明确标注为内部。
- [ ] 报告/API/任务/路由契约没有破坏性变化。
- [ ] 新增测试在旧实现上会失败，在当前实现上通过。
- [ ] 没有提交 `.env`、运行时产物或构建产物。
- [ ] PR 描述写清验证命令与真实链路结果。
