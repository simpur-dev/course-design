# 引据 Web 工作台

React 19 + Vite 8 + TypeScript，无外部 UI 组件库。构建产物 `dist/` 由 FastAPI 同源托管。

```bash
npm install
npm run dev      # 5173，/api 代理到 127.0.0.1:8787
npm run lint     # oxlint
npm run build    # tsc -b && vite build
```

路由为 hash 形式：`#/` 核对台、`#/papers` 论文库、`#/reports` 报告列表、`#/reports/:runId` 详情、`#/memory` 项目记忆、`#/system` 系统状态。`#/memory?project=<id>` 可从报告详情直达对应项目。

目录：

- `src/api.ts`：接口封装与 `ApiError`；
- `src/types.ts`：后端 JSON 类型；
- `src/format.ts`：时间、百分比、判定/阶段/置信度文案；
- `src/components/ReportView.tsx`：报告摘要、记忆写入条与主张卡片；
- `src/components/EvidenceDrawer.tsx`：证据与检索路径抽屉（portal 到 body）；
- `src/pages/`：六个页面（核对台、论文库、报告列表、报告详情、项目记忆、系统状态）；
- `src/index.css`：暖纸色设计变量、布局与响应式样式。

记忆页展示项目 Scope、四类条目、最近 Handoff 与证据检查，支持显式写入、召回测试与 `continue latest` 恢复；`GET /api/memory` 接受 `project`、`kind`、`limit`（默认 20、上限 200）与 `offset`，返回当前页 `entries` 及全量 `total`/`counts`/`has_more`，页面按页追加并按 `artifact_id` 去重。对应的接口为 `GET /api/memory/projects`、`GET /api/memory`、`POST /api/memory/entries`、`GET /api/memory/search`、`POST /api/memory/handoff/continue`。

开发时先启动后端 `uv run yinju serve`，再运行 `npm run dev`。
