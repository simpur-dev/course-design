import { useCallback, useEffect, useState } from 'react'
import { asApiError, getConfig, getHealth, type ApiError } from './api'
import { AuditPage } from './pages/AuditPage'
import { MemoryPage } from './pages/MemoryPage'
import { PapersPage } from './pages/PapersPage'
import { ReportDetailPage } from './pages/ReportDetailPage'
import { ReportsPage } from './pages/ReportsPage'
import { SystemPage } from './pages/SystemPage'
import type { AppConfig, Health } from './types'

function normalizeHash(hash: string): string {
  const raw = hash.replace(/^#/, '')
  return raw.startsWith('/') ? raw : `/${raw}`
}

function useHashRoute(): string {
  const [route, setRoute] = useState(() => normalizeHash(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(normalizeHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [route])
  return route
}

export default function App() {
  const route = useHashRoute()
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [statusError, setStatusError] = useState<ApiError | null>(null)

  const refreshStatus = useCallback(() => {
    Promise.all([getConfig(), getHealth()])
      .then(([configPayload, healthPayload]) => {
        setConfig(configPayload)
        setHealth(healthPayload)
        setStatusError(null)
      })
      .catch((cause) => setStatusError(asApiError(cause)))
  }, [])

  useEffect(() => {
    refreshStatus()
    const timer = window.setInterval(refreshStatus, 60_000)
    return () => window.clearInterval(timer)
  }, [refreshStatus])

  const checks = health?.checks ?? []
  const environmentState = statusError
    ? 'bad'
    : health === null
      ? 'wait'
      : health.ok
        ? 'ok'
        : 'bad'
  const environmentLabel = statusError
    ? '服务未连接'
    : health === null
      ? '检查中'
      : health.ok
        ? '环境正常'
        : '环境异常'
  const environmentDetail = checks.length
    ? checks.map((check) => `${check.name} ${check.ok ? '通过' : '失败'}`).join(' · ')
    : statusError?.message ?? '正在读取本地服务状态'

  const reportMatch = route.match(/^\/reports\/([^/]+)$/)
  let runId: string | null = null
  if (reportMatch) {
    try {
      runId = decodeURIComponent(reportMatch[1])
    } catch {
      runId = reportMatch[1]
    }
  }

  const demoRoute = route === '/audit/demo'
  const memoryRoute = route === '/memory' || route.startsWith('/memory?')
  let memoryProject: string | null = null
  if (memoryRoute) {
    const queryStart = route.indexOf('?')
    if (queryStart >= 0) {
      memoryProject = new URLSearchParams(route.slice(queryStart + 1)).get('project')
    }
  }

  const pageTitle =
    demoRoute
      ? '数据库示例'
      : route === '/'
      ? '核对台'
      : route === '/papers'
        ? '论文库'
        : route === '/reports'
          ? '核对报告'
          : runId
            ? '报告详情'
            : memoryRoute
              ? '项目记忆'
              : route === '/system'
                ? '系统状态'
                : '页面不存在'

  useEffect(() => {
    document.title = `${pageTitle} · 引据 CitationProof`
  }, [pageTitle])

  let page = <AuditPage config={config} demo={demoRoute} />
  if (route === '/papers') {
    page = <PapersPage />
  } else if (route === '/reports') {
    page = <ReportsPage />
  } else if (runId) {
    page = <ReportDetailPage key={runId} runId={runId} />
  } else if (memoryRoute) {
    page = <MemoryPage key={memoryProject ?? ''} initialProject={memoryProject} />
  } else if (route === '/system') {
    page = <SystemPage config={config} health={health} onRefresh={refreshStatus} />
  } else if (route !== '/' && !demoRoute) {
    page = (
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
    )
  }

  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main"
        onClick={(event) => {
          event.preventDefault()
          const main = document.getElementById('main')
          main?.focus()
          main?.scrollIntoView({ block: 'start' })
        }}
      >
        跳到主要内容
      </a>
      <header className="site-header">
        <div className="header-inner">
          <a className="brand" href="#/">
            <span className="brand-mark" aria-hidden="true">
              引
            </span>
            <span className="brand-text">
              <strong>引据</strong>
              <span className="brand-sub">CitationProof</span>
            </span>
          </a>
          <nav className="main-nav" aria-label="主导航">
            <a
              className={route === '/' || demoRoute ? 'active' : ''}
              aria-current={route === '/' || demoRoute ? 'page' : undefined}
              href="#/"
            >
              核对台
            </a>
            <a
              className={route.startsWith('/papers') ? 'active' : ''}
              aria-current={route.startsWith('/papers') ? 'page' : undefined}
              href="#/papers"
            >
              论文库
            </a>
            <a
              className={route.startsWith('/reports') ? 'active' : ''}
              aria-current={route.startsWith('/reports') ? 'page' : undefined}
              href="#/reports"
            >
              核对报告
            </a>
            <a
              className={memoryRoute ? 'active' : ''}
              aria-current={memoryRoute ? 'page' : undefined}
              href="#/memory"
            >
              项目记忆
            </a>
          </nav>
          <div className="header-status">
            <a
              className={`env-status env-status-${environmentState}${
                route.startsWith('/system') ? ' is-current' : ''
              }`}
              href="#/system"
              aria-current={route.startsWith('/system') ? 'page' : undefined}
              aria-label={`系统状态：${environmentLabel}`}
              title={environmentDetail}
            >
              <span className="status-dot" aria-hidden="true" />
              {environmentLabel}
            </a>
          </div>
        </div>
      </header>

      <div className="sub-strip">
        <div className="sub-strip-inner">
          <span>每一句引用，都能落回原文</span>
          <span className="strip-sep" aria-hidden="true">
            ·
          </span>
          <span>检索限定在被引论文内</span>
          <span className="strip-sep" aria-hidden="true">
            ·
          </span>
          <span>
            {statusError
              ? '本地服务未连接'
              : health === null
                ? '正在读取运行状态'
                : health.ok
                  ? '结论、页码与检索路径可回查'
                  : '环境检查存在失败项'}
          </span>
        </div>
      </div>

      <main className="site-main" id="main" tabIndex={-1}>
        {statusError ? (
          <div className="notice error" role="alert">
            <strong>无法连接本地服务</strong>
            <p>{statusError.message}</p>
            {statusError.hint ? <p className="hint">{statusError.hint}</p> : null}
            <p className="mono small">yinju serve</p>
          </div>
        ) : null}
        {page}
      </main>

      <footer className="site-footer">
        <div className="footer-inner">
          <span>引据 CitationProof · 主张 → 原文证据 → 引用核对</span>
          <span className="muted">
            {config ? `v${config.version} · ` : ''}
            seekdb + PowerContext · 本机工作台
          </span>
        </div>
      </footer>
    </div>
  )
}
