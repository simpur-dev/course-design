import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import {
  asApiError,
  continueMemoryHandoff,
  getMemory,
  getMemoryProjects,
  searchMemory,
  writeMemory,
  type ApiError,
} from '../../shared/api'
import { formatNumber } from '../../shared/format'
import type {
  HandoffView,
  MemoryEntryRecord,
  MemoryKind,
  MemoryPayload,
  MemoryProject,
  MemorySearchHit,
} from '../../shared/types'

const KIND_ORDER: MemoryKind[] = ['criterion', 'decision', 'constraint', 'next_step']
const PAGE_SIZE = 20

const KIND_LABELS: Record<string, string> = {
  criterion: '核对标准',
  decision: '判断',
  constraint: '范围约束',
  next_step: '下一步',
}

const DISPOSITION_LABELS: Record<string, string> = {
  continuable: '可继续',
  blocked: '受阻',
  complete: '已完成',
}

function KindChip({ kind }: { kind: string }) {
  return <span className={`kind-chip kind-${kind}`}>{KIND_LABELS[kind] ?? kind}</span>
}

function HandoffPanel({
  handoff,
  onResume,
  resuming,
  notice,
}: {
  handoff: HandoffView
  onResume: () => void
  resuming: boolean
  notice: string | null
}) {
  const content = handoff.content
  const evidenceChecks = handoff.evidence_checks
  const unavailable = evidenceChecks.filter((check) => check.status !== 'available')
  const allAvailable = evidenceChecks.length > 0 && unavailable.length === 0

  return (
    <section className="card handoff-card">
      <div className="card-head">
        <div>
          <h2>上次核对的交接</h2>
          <p className="muted small handoff-sub">从这里接着做，不用重新翻论文。</p>
        </div>
        <div className="handoff-head-meta">
          <span className={`status-pill ${handoff.status === 'resolved' ? 'ok' : 'wait'}`}>
            {handoff.status === 'resolved' ? '已续接' : '待续接'}
          </span>
          {content ? (
            <button
              type="button"
              className="button primary"
              onClick={onResume}
              disabled={resuming}
            >
              {resuming ? '正在续接…' : '继续上次核对'}
            </button>
          ) : null}
        </div>
      </div>

      {content ? (
        <>
          <p className="handoff-objective">{content.objective}</p>
          <div className="handoff-tags">
            <span className={`tag handoff-${content.disposition}`}>
              {DISPOSITION_LABELS[content.disposition] ?? content.disposition}
            </span>
            {evidenceChecks.length > 0 ? (
              <span className={`tag ${allAvailable ? 'handoff-verified' : 'handoff-warning'}`}>
                {allAvailable ? '交接引用可用' : `${unavailable.length} 组引用不可用`}
              </span>
            ) : null}
          </div>
          <p className="handoff-trust">
            交接只作为续接线索，不作为证据；引用的记忆会逐条检查是否仍可用。
          </p>
          {notice ? <p className="handoff-notice">{notice}</p> : null}

          {content.state.length > 0 ? (
            content.state.length === 1 ? (
              <p className="handoff-state-summary">{content.state[0].text}</p>
            ) : (
              <>
                <p className="handoff-state-summary">{content.state[0].text}</p>
                <details className="handoff-state-wrap">
                  <summary>交接明细（{content.state.length - 1} 条）</summary>
                  <ol className="handoff-state">
                    {content.state.slice(1).map((statement, index) => (
                      <li key={`${index + 1}-${statement.text.slice(0, 20)}`}>
                        <p>{statement.text}</p>
                      </li>
                    ))}
                  </ol>
                </details>
              </>
            )
          ) : null}

          <div className="handoff-next">
            <span className="eyebrow">下一步</span>
            <p>{content.next_action.text}</p>
          </div>

          {content.omissions.length > 0 ? (
            <div className="handoff-omissions">
              <span className="eyebrow">未列入交接</span>
              {content.omissions.map((omission) => (
                <p key={omission.text}>{omission.text}</p>
              ))}
            </div>
          ) : null}

          {evidenceChecks.length > 0 ? (
            <details className="handoff-tech">
              <summary>交接引用检查（{evidenceChecks.length}）</summary>
              <ul>
                {evidenceChecks.map((check, index) => (
                  <li key={`${check.claim}-${index}`}>
                    <span className={`evidence-status evidence-${check.status}`}>
                      {check.status === 'available' ? '可用' : '缺失'}
                    </span>
                    <span>
                      {check.claim === 'next_action'
                        ? '下一步'
                        : `状态 ${(check.state_index ?? 0) + 1}`}
                    </span>
                    {check.unavailable_evidence.length > 0 ? (
                      <span className="muted small">
                        缺失 {check.unavailable_evidence.length} 条
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </>
      ) : (
        <div className="handoff-empty">
          <p>这个项目还没有交接记录。</p>
          <p className="muted small">
            运行一次核对后，判断、下一步和交接会自动留在这里，下次可以直接接着做。
          </p>
          <a className="button ghost" href="#/">
            去核对台
          </a>
        </div>
      )}
    </section>
  )
}

export function MemoryPage({ initialProject }: { initialProject?: string | null }) {
  const [projects, setProjects] = useState<MemoryProject[]>([])
  const [project, setProject] = useState('')
  const [kind, setKind] = useState<MemoryKind | 'all'>('all')
  const [payload, setPayload] = useState<MemoryPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiError | null>(null)
  const [reload, setReload] = useState(0)

  const [formKind, setFormKind] = useState<MemoryKind>('criterion')
  const [text, setText] = useState('')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [writeNotice, setWriteNotice] = useState<string | null>(null)
  const [writeError, setWriteError] = useState<ApiError | null>(null)

  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<ApiError | null>(null)
  const [hits, setHits] = useState<MemorySearchHit[] | null>(null)

  const [resuming, setResuming] = useState(false)
  const [resumeNotice, setResumeNotice] = useState<string | null>(null)
  const [entries, setEntries] = useState<MemoryEntryRecord[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [loadMoreError, setLoadMoreError] = useState<ApiError | null>(null)
  const [recentEntries, setRecentEntries] = useState<MemoryEntryRecord[]>([])
  const queryKey = `${project}|${kind}|${reload}`
  const queryKeyRef = useRef(queryKey)

  useEffect(() => {
    let cancelled = false
    getMemoryProjects()
      .then((data) => {
        if (cancelled) {
          return
        }
        setProjects(data.projects)
        setProject((current) => {
          if (current) {
            return current
          }
          if (initialProject && data.projects.some((item) => item.project === initialProject)) {
            return initialProject
          }
          return data.default || data.projects[0]?.project || ''
        })
        setError(null)
        if (data.projects.length === 0) {
          setLoading(false)
        }
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(asApiError(cause))
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [reload, initialProject])

  useEffect(() => {
    queryKeyRef.current = queryKey
    if (!project) {
      return
    }
    let cancelled = false
    getMemory(project, kind === 'all' ? null : kind, PAGE_SIZE, 0)
      .then((data) => {
        if (cancelled) {
          return
        }
        setPayload(data)
        setEntries(data.entries)
        setHasMore(data.has_more)
        setLoadMoreError(null)
        setError(null)
        setLoading(false)
        setRefreshing(false)
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(asApiError(cause))
          setLoading(false)
          setRefreshing(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [project, kind, reload, queryKey])

  async function onWrite(event: FormEvent) {
    event.preventDefault()
    if (!text.trim() || !project) {
      return
    }
    setSaving(true)
    setWriteNotice(null)
    setWriteError(null)
    try {
      const result = await writeMemory({
        project,
        kind: formKind,
        text: text.trim(),
        reason: reason.trim() || undefined,
      })
      setWriteNotice(
        result.changed
          ? `已留给下次 ${result.records.length} 条，已置顶显示。`
          : '内容没有变化，未新增条目。',
      )
      setText('')
      setReason('')
      if (result.changed) {
        setRecentEntries(result.records)
        setRefreshing(true)
        setLoadMoreError(null)
        setReload((value) => value + 1)
      }
    } catch (cause) {
      setWriteError(asApiError(cause))
    } finally {
      setSaving(false)
    }
  }

  async function onLoadMore() {
    if (!project || loading || loadingMore || refreshing || !hasMore) {
      return
    }
    const activeKey = queryKeyRef.current
    setLoadingMore(true)
    setLoadMoreError(null)
    try {
      const data = await getMemory(
        project,
        kind === 'all' ? null : kind,
        PAGE_SIZE,
        entries.length,
      )
      if (queryKeyRef.current !== activeKey) {
        return
      }
      setEntries((current) => {
        const seen = new Set(current.map((entry) => entry.artifact_id))
        return [
          ...current,
          ...data.entries.filter((entry) => !seen.has(entry.artifact_id)),
        ]
      })
      setHasMore(data.has_more)
      setPayload((current) =>
        current
          ? { ...current, total: data.total, counts: data.counts, has_more: data.has_more }
          : data,
      )
    } catch (cause) {
      if (queryKeyRef.current === activeKey) {
        setLoadMoreError(asApiError(cause))
      }
    } finally {
      if (queryKeyRef.current === activeKey) {
        setLoadingMore(false)
      }
    }
  }

  async function onSearch(event: FormEvent) {
    event.preventDefault()
    if (!query.trim() || !project) {
      return
    }
    setSearching(true)
    setSearchError(null)
    try {
      const result = await searchMemory(project, query.trim())
      setHits(result.hits)
    } catch (cause) {
      setSearchError(asApiError(cause))
    } finally {
      setSearching(false)
    }
  }

  async function onResume() {
    if (!project) {
      return
    }
    setResuming(true)
    setResumeNotice(null)
    try {
      const result = await continueMemoryHandoff(project)
      setPayload((current) => (current ? { ...current, handoff: result.handoff } : current))
      setResumeNotice(
        result.handoff.status === 'empty'
          ? '当前项目还没有可恢复的交接。'
          : `已从 r${result.handoff.current_revision?.revision ?? '—'} 续接；信任级别 ${
              result.handoff.trust
            }。`,
      )
    } catch (cause) {
      setResumeNotice(asApiError(cause).message)
    } finally {
      setResuming(false)
    }
  }

  const tabs: (MemoryKind | 'all')[] = ['all', ...KIND_ORDER]
  const counts = payload?.counts ?? {}
  const recentIds = recentEntries.map((entry) => entry.artifact_id)
  const orderedEntries = useMemo(() => {
    const pinned = recentEntries.filter((entry) => kind === 'all' || entry.kind === kind)
    const pinnedIds = new Set(pinned.map((entry) => entry.artifact_id))
    return [...pinned, ...entries.filter((entry) => !pinnedIds.has(entry.artifact_id))]
  }, [entries, recentEntries, kind])

  return (
    <div className="memory-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Project memory</p>
          <h1>项目记忆</h1>
          <p className="page-sub">
            核对标准、逐条判断和下一步都留在这里；下次从最近交接接着做。
          </p>
        </div>
        <div className="page-actions">
          <label className="field inline-field">
            <span>项目</span>
            <select
              value={project}
              onChange={(event) => {
                setProject(event.target.value)
                setPayload(null)
                setLoading(true)
                setHits(null)
                setResumeNotice(null)
                setEntries([])
                setHasMore(false)
                setLoadingMore(false)
                setLoadMoreError(null)
                setRecentEntries([])
              }}
              disabled={projects.length === 0}
            >
              {projects.length === 0 ? <option value="">暂无项目</option> : null}
              {projects.map((item) => (
                <option value={item.project} key={item.project}>
                  {item.project}
                  {item.scope_id ? '' : ' · 待创建 Scope'}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="button ghost"
            disabled={loading}
            onClick={() => {
              setLoading(true)
              setLoadingMore(false)
              setLoadMoreError(null)
              setReload((value) => value + 1)
            }}
          >
            {loading ? '刷新中…' : '刷新'}
          </button>
        </div>
      </header>

      {error ? (
        <div className="notice error" role="alert">
          <strong>无法读取项目记忆</strong>
          <p>{error.message}</p>
          {error.hint ? <p className="hint">{error.hint}</p> : null}
        </div>
      ) : null}

      {loading && !payload ? (
        <p className="loading-line" role="status">
          正在读取项目记忆…
        </p>
      ) : null}

      {payload ? (
        <>
          <div className="memory-grid">
            <HandoffPanel
              handoff={payload.handoff}
              onResume={onResume}
              resuming={resuming}
              notice={resumeNotice}
            />

            <section
              className={`card memory-entries${loading && payload ? ' is-filtering' : ''}`}
              aria-busy={loading && Boolean(payload)}
            >
              <div className="card-head">
                <h2>核对留下的判断</h2>
                <span className="muted small" role="status">
                  {loading && payload
                    ? '正在读取…'
                    : `显示 ${formatNumber(Math.min(orderedEntries.length, payload.total))} / ${formatNumber(payload.total)} 条`}
                </span>
              </div>
              <div className="kind-tabs" role="tablist" aria-label="记忆类型">
                {tabs.map((item) => (
                  <button
                    type="button"
                    role="tab"
                    aria-selected={kind === item}
                    className={kind === item ? 'active' : ''}
                    key={item}
                    onClick={() => {
                      if (item === kind) {
                        return
                      }
                      setKind(item)
                      setLoading(true)
                      setHasMore(false)
                      setLoadingMore(false)
                      setLoadMoreError(null)
                    }}
                  >
                    {item === 'all' ? '全部' : KIND_LABELS[item]}
                    <span className="tab-count">
                      {item === 'all'
                        ? KIND_ORDER.reduce((sum, key) => sum + (counts[key] ?? 0), 0)
                        : counts[item] ?? 0}
                    </span>
                  </button>
                ))}
              </div>

              {orderedEntries.length === 0 ? (
                <div className="memory-empty">
                  <p>这个项目还没有留下判断。</p>
                  <p className="muted small">运行一次核对，或写一条标准留在这里。</p>
                </div>
              ) : (
                <>
                  <ul className="memory-list">
                    {orderedEntries.map((entry) => (
                      <li
                        className={`memory-entry${recentIds.includes(entry.artifact_id) ? ' is-pinned' : ''}`}
                        key={entry.artifact_id}
                      >
                        <div className="memory-entry-head">
                          <KindChip kind={entry.kind} />
                          {recentIds.includes(entry.artifact_id) ? (
                            <span className="tag pinned-tag">刚刚写入</span>
                          ) : null}
                        </div>
                        <p className="memory-text">{entry.text}</p>
                        <details className="entry-tech">
                          <summary>技术信息</summary>
                          <div className="entry-tech-body">
                            <span className="mono">{entry.artifact_id}</span>
                            <span>版本 r{entry.revision}</span>
                            <span>状态 {entry.state}</span>
                          </div>
                        </details>
                      </li>
                    ))}
                  </ul>
                  {hasMore ? (
                    <div className="memory-more">
                      {loadMoreError ? (
                        <p className="error-line" role="alert">
                          {loadMoreError.message}
                          {loadMoreError.hint ? ` · ${loadMoreError.hint}` : ''}
                        </p>
                      ) : null}
                      <button
                        type="button"
                        className="button ghost"
                        onClick={onLoadMore}
                        disabled={loadingMore || loading || refreshing}
                      >
                        {loadingMore
                          ? '加载中…'
                          : refreshing
                            ? '正在同步…'
                            : `加载更多（还有 ${formatNumber(
                              Math.max(payload.total - orderedEntries.length, 0),
                            )} 条）`}
                      </button>
                    </div>
                  ) : orderedEntries.length > PAGE_SIZE ? (
                    <p className="memory-more-hint muted small">
                      已显示全部 {formatNumber(orderedEntries.length)} 条
                    </p>
                  ) : null}
                </>
              )}
            </section>

            <section className="card memory-write">
              <div className="card-head">
                <div>
                  <h2>给下次留一条</h2>
                  <p className="muted small write-hint">
                    只写你确认过的标准或判断，不自动抽取模型猜测。
                  </p>
                </div>
              </div>
              <form onSubmit={onWrite}>
                <label className="field">
                  <span>这是</span>
                  <select
                    value={formKind}
                    onChange={(event) => setFormKind(event.target.value as MemoryKind)}
                  >
                    {KIND_ORDER.map((item) => (
                      <option value={item} key={item}>
                        {KIND_LABELS[item]}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>内容</span>
                  <textarea
                    value={text}
                    onChange={(event) => setText(event.target.value)}
                    rows={4}
                    maxLength={2000}
                    placeholder="例如：GLUE 结果必须给出具体分数与表格位置。"
                    disabled={saving}
                  />
                </label>
                <label className="field">
                  <span>为什么记下（可选）</span>
                  <input
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    maxLength={500}
                    placeholder="例如：这次复核后确认的口径"
                    disabled={saving}
                  />
                </label>
                {writeError ? (
                  <p className="error-line" role="alert">
                    {writeError.message}
                    {writeError.hint ? ` · ${writeError.hint}` : ''}
                  </p>
                ) : null}
                {writeNotice ? (
                  <p className="form-notice" role="status">
                    {writeNotice}
                  </p>
                ) : null}
                <button
                  type="submit"
                  className="button primary"
                  disabled={saving || !text.trim()}
                >
                  {saving ? '保存中…' : '留给下次'}
                </button>
              </form>
            </section>
          </div>

          <details className="card memory-advanced">
            <summary>
              <span>高级：记忆库信息与检索</span>
              <span className="muted small advanced-hint">Scope、分类统计、全文检索</span>
            </summary>
            <div className="memory-advanced-body">
              <div className="memory-scope">
                <div>
                  <span className="eyebrow">记忆库范围</span>
                  <p className="scope-title mono">{payload.scope.title}</p>
                  <p className="muted small mono">{payload.scope.scope_id}</p>
                </div>
                <p className="muted small scope-summary">{payload.scope.summary}</p>
              </div>

              <section className="memory-stats">
                <div className="stat-card card">
                  <span className="stat-value">{formatNumber(payload.total)}</span>
                  <span className="stat-label">当前筛选</span>
                </div>
                {KIND_ORDER.map((item) => (
                  <div className="stat-card card" key={item}>
                    <span className="stat-value">{formatNumber(counts[item] ?? 0)}</span>
                    <span className="stat-label">{KIND_LABELS[item]}</span>
                  </div>
                ))}
              </section>

              <section className="memory-search">
                <div className="card-head">
                  <h2>检索项目记忆</h2>
                  <span className="muted small">PowerContext 全文检索</span>
                </div>
                <form className="search-form" onSubmit={onSearch}>
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    maxLength={500}
                    placeholder="输入关键词，例如：页码、BERT、复核"
                    disabled={searching}
                    aria-label="记忆检索关键词"
                  />
                  <button
                    type="submit"
                    className="button ghost"
                    disabled={searching || !query.trim()}
                  >
                    {searching ? '检索中…' : '检索'}
                  </button>
                </form>
                {searchError ? (
                  <p className="error-line" role="alert">
                    {searchError.message}
                    {searchError.hint ? ` · ${searchError.hint}` : ''}
                  </p>
                ) : null}
                {hits !== null ? (
                  hits.length === 0 ? (
                    <p className="muted small">没有匹配的记忆。</p>
                  ) : (
                    <ul className="search-hits">
                      {hits.map((hit) => (
                        <li key={hit.memory.artifact.artifact_id}>
                          <div className="memory-entry-head">
                            <KindChip kind={hit.memory.kind} />
                            <span className="muted small">
                              相关度 {hit.score.toFixed(3)}
                            </span>
                            <span className="muted small">
                              {hit.matched_by.join(' + ')}
                            </span>
                          </div>
                          <p className="memory-text">{hit.memory.text}</p>
                          <p className="muted small mono search-hit-id">
                            {hit.memory.artifact.artifact_id}
                          </p>
                        </li>
                      ))}
                    </ul>
                  )
                ) : null}
              </section>
            </div>
          </details>
        </>
      ) : null}
    </div>
  )
}
