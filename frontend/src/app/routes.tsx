import type { ReactNode } from 'react'
import { AuditPage } from '../features/audit/AuditPage'
import { MemoryPage } from '../features/memory/MemoryPage'
import { PapersPage } from '../features/papers/PapersPage'
import { ReportDetailPage } from '../features/reports/ReportDetailPage'
import { ReportsPage } from '../features/reports/ReportsPage'
import { SystemPage } from '../features/system/SystemPage'
import type { AppConfig, Health } from '../shared/types'
import type { NavKey } from './navigation'
import type { RouteState } from './router'

export interface RouteView {
  title: string
  nav: NavKey | null
  element: ReactNode
}

export interface RouteContext {
  config: AppConfig | null
  health: Health | null
  refreshStatus: () => void
}

export function resolveRoute(route: RouteState, context: RouteContext): RouteView {
  switch (route.name) {
    case 'audit':
      return {
        title: route.demo ? '数据库示例' : '核对台',
        nav: 'audit',
        element: <AuditPage config={context.config} demo={route.demo} />,
      }
    case 'papers':
      return { title: '论文库', nav: 'papers', element: <PapersPage /> }
    case 'reports':
      return { title: '核对报告', nav: 'reports', element: <ReportsPage /> }
    case 'report':
      return {
        title: '报告详情',
        nav: 'reports',
        element: <ReportDetailPage key={route.runId} runId={route.runId} />,
      }
    case 'memory':
      return {
        title: '项目记忆',
        nav: 'memory',
        element: <MemoryPage key={route.project ?? ''} initialProject={route.project} />,
      }
    case 'system':
      return {
        title: '系统状态',
        nav: null,
        element: (
          <SystemPage
            config={context.config}
            health={context.health}
            onRefresh={context.refreshStatus}
          />
        ),
      }
    default:
      return {
        title: '页面不存在',
        nav: null,
        element: (
          <section className="empty-state card">
            <div className="empty-mark" aria-hidden="true">
              空
            </div>
            <h1>页面不存在</h1>
            <p>这个地址没有对应的页面。</p>
            <a className="button primary" href="#/">
              回到核对台
            </a>
          </section>
        ),
      }
  }
}
