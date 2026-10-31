import { useEffect } from 'react'
import { useAppStatus } from '../shared/hooks/useAppStatus'
import { useHashRoute } from '../shared/hooks/useHashRoute'
import { NAV_ITEMS } from './navigation'
import { parseRoute } from './router'
import { resolveRoute } from './routes'

export default function App() {
  const route = useHashRoute()
  const status = useAppStatus()
  const state = parseRoute(route)
  const view = resolveRoute(state, {
    config: status.config,
    health: status.health,
    refreshStatus: status.refresh,
  })

  useEffect(() => {
    document.title = `${view.title} · 引据 CitationProof`
  }, [view.title])

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
            {NAV_ITEMS.map((item) => {
              const active = item.isActive(state)
              return (
                <a
                  key={item.key}
                  className={active ? 'active' : ''}
                  aria-current={active ? 'page' : undefined}
                  href={item.href}
                >
                  {item.label}
                </a>
              )
            })}
          </nav>
          <div className="header-status">
            <a
              className={`env-status env-status-${status.environmentState}${
                state.name === 'system' ? ' is-current' : ''
              }`}
              href="#/system"
              aria-current={state.name === 'system' ? 'page' : undefined}
              aria-label={`系统状态：${status.environmentLabel}`}
              title={status.environmentDetail}
            >
              <span className="status-dot" aria-hidden="true" />
              {status.environmentLabel}
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
            {status.error
              ? '本地服务未连接'
              : status.health === null
                ? '正在读取运行状态'
                : status.health.ok
                  ? '结论、页码与检索路径可回查'
                  : '环境检查存在失败项'}
          </span>
        </div>
      </div>

      <main className="site-main" id="main" tabIndex={-1}>
        {status.error ? (
          <div className="notice error" role="alert">
            <strong>无法连接本地服务</strong>
            <p>{status.error.message}</p>
            {status.error.hint ? <p className="hint">{status.error.hint}</p> : null}
            <p className="mono small">citationproof serve</p>
          </div>
        ) : null}
        {view.element}
      </main>

      <footer className="site-footer">
        <div className="footer-inner">
          <span>引据 CitationProof · 主张 → 原文证据 → 引用核对</span>
          <span className="muted">
            {status.config ? `v${status.config.version} · ` : ''}
            seekdb + PowerContext · 本机工作台
          </span>
        </div>
      </footer>
    </div>
  )
}
