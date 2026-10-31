# 引据前端工作台

React 19 + Vite 8 + TypeScript，无外部 UI 组件库。构建产物 `dist/` 由 FastAPI 同源托管。

```bash
npm install
npm run dev      # 5173，/api 代理到 127.0.0.1:8787
npm run lint     # oxlint
npm run build    # tsc -b && vite build
```

路由为 hash 形式：`#/` 核对台、`#/audit/demo` 内置示例、`#/papers` 论文库、`#/reports` 报告列表、`#/reports/:runId` 详情、`#/memory` 项目记忆、`#/system` 系统状态。`#/memory?project=<id>` 可从报告详情直达对应项目。

## 目录与边界

```text
src/
├── main.tsx                     # React 挂载点
├── app/                         # 应用外壳：路由、导航、页面装配、全局样式
│   ├── App.tsx
│   ├── router.ts                # hash → RouteState
│   ├── routes.tsx               # RouteState → 页面与标题
│   ├── navigation.ts            # 主导航注册表
│   └── styles/index.css
├── shared/                      # 跨 feature 的稳定能力
│   ├── api/                     # client.ts（请求/错误）+ endpoints.ts（端点）
│   ├── hooks/                   # useHashRoute、useAppStatus
│   ├── format.ts                # 时间、百分比、判定/阶段/置信度文案
│   └── types.ts                 # 后端 JSON 类型
└── features/
    ├── audit/                   # 核对台：选草稿/论文库、任务进度、报告预览
    ├── papers/                  # 论文库与 PDF 上传
    ├── reports/                 # 报告列表/详情 + ReportView、EvidenceDrawer
    ├── memory/                  # 项目记忆、Handoff、召回测试
    └── system/                  # 服务状态与任务记录
```

依赖规则：

- `app` 可以引用 `shared` 与任意 `features`；
- `features` 只能引用 `shared`，另允许 `audit → reports` 复用 `ReportView`；
- 新增页面时，在 `app/router.ts` 增加路由状态、在 `app/routes.tsx` 注册视图，并在 `app/navigation.ts` 决定是否进入主导航；
- 新增接口时先加 `shared/api/endpoints.ts` 与 `shared/types.ts`，页面不直接 `fetch`。

记忆页展示项目 Scope、四类条目、最近 Handoff 与证据检查，支持显式写入、召回测试与 `continue latest` 恢复；`GET /api/memory` 接受 `project`、`kind`、`limit`（默认 20、上限 200）与 `offset`，返回当前页 `entries` 及全量 `total`/`counts`/`has_more`，页面按页追加并按 `artifact_id` 去重。

开发时先启动后端 `uv run citationproof serve`，再运行 `npm run dev`。
