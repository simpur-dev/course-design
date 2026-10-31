import { useEffect, useState } from 'react'
import { asApiError, getJobs, type ApiError } from '../api'
import { formatTime, stageLabel } from '../format'
import type { AppConfig, Health, Job } from '../types'

const CHECK_LABELS: Record<string, string> = {
  data: '数据目录',
  seekdb: 'seekdb',
  powercontext: 'PowerContext',
  providers: '模型配置',
}

const JOB_LABELS: Record<string, string> = {
  queued: '排队',
  running: '运行中',
  succeeded: '成功',
  failed: '失败',
}

export function SystemPage({
  config,
  health,
  onRefresh,
}: {
  config: AppConfig | null
  health: Health | null
  onRefresh: () => void
}) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    getJobs()
      .then((payload) => {
        if (!cancelled) {
          setJobs(payload.jobs)
          setError(null)
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
  }, [])

  const hasActiveJobs = jobs.some((job) => job.status === 'queued' || job.status === 'running')
  useEffect(() => {
    if (!hasActiveJobs) {
      return
    }
    let cancelled = false
    const timer = window.setInterval(() => {
      getJobs()
        .then((payload) => {
          if (!cancelled) {
            setJobs(payload.jobs)
            setError(null)
          }
        })
        .catch((cause) => {
          if (!cancelled) {
            setError(asApiError(cause))
          }
        })
    }, 1500)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [hasActiveJobs])

  return (
    <div className="system-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Runtime</p>
          <h1>系统状态</h1>
          <p className="page-sub">
            核对依赖 seekdb（证据库）与 PowerContext（研究记忆）。这里展示本次运行的实时自检与任务记录。
          </p>
        </div>
        <button
          type="button"
          className="button ghost"
          disabled={loading}
          onClick={() => {
            onRefresh()
            setLoading(true)
            getJobs()
              .then((payload) => {
                setJobs(payload.jobs)
                setError(null)
              })
              .catch((cause) => setError(asApiError(cause)))
              .finally(() => setLoading(false))
          }}
        >
          {loading ? '自检中…' : '重新自检'}
        </button>
      </header>

      <div className="system-grid">
        <section className="card">
          <div className="card-head">
            <h2>运行配置</h2>
            <span className="muted small">v{config?.version ?? '—'}</span>
          </div>
          <dl className="meta-list vertical">
            <div>
              <dt>判定器</dt>
              <dd className="mono">{config?.verifier ?? '—'}</dd>
            </div>
            <div>
              <dt>判定模型</dt>
              <dd className="mono">{config?.verifier_model ?? '未配置'}</dd>
            </div>
            <div>
              <dt>向量提供方</dt>
              <dd className="mono">{config?.embedding_provider ?? '—'}</dd>
            </div>
            <div>
              <dt>无 key 基线</dt>
              <dd>{config?.baseline ? '是（不出具 supported）' : '否'}</dd>
            </div>
            <div>
              <dt>项目记忆</dt>
              <dd>
                {config === null
                  ? '—'
                  : config.memory_enabled
                    ? '写入 PowerContext'
                    : '已关闭（YINJU_MEMORY_ENABLED=false）'}
              </dd>
            </div>
            <div>
              <dt>前端构建</dt>
              <dd>{config?.web_built ? '已构建' : '未构建'}</dd>
            </div>
          </dl>
          {config?.baseline ? <p className="baseline-inline">{config.baseline_notice}</p> : null}
          <div className="download-row">
            <a className="text-link" href="/api/docs" target="_blank" rel="noreferrer">
              API 文档
            </a>
            <a className="text-link" href="/api/openapi.json" target="_blank" rel="noreferrer">
              OpenAPI
            </a>
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <h2>自检</h2>
            <span className={`status-pill ${health?.ok ? 'ok' : 'bad'}`}>
              {health === null ? '读取中' : health.ok ? '全部通过' : '存在失败项'}
            </span>
          </div>
          {health === null ? (
            <p className="muted">正在读取自检结果…</p>
          ) : (
            <ul className="check-list-simple">
              {health.checks.map((check) => (
                <li key={check.name} className={check.ok ? 'check-ok' : 'check-bad'}>
                  <div className="check-line">
                    <span className="check-name">{CHECK_LABELS[check.name] ?? check.name}</span>
                    <span className="check-state">{check.ok ? '通过' : '失败'}</span>
                  </div>
                  <p className="check-detail">{check.detail}</p>
                  {check.hint ? <p className="hint mono">{check.hint}</p> : null}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="card">
        <div className="card-head">
          <h2>本次会话任务</h2>
          <span className="muted small">内存记录，重启服务后清空</span>
        </div>
        {error ? (
          <div className="notice error" role="alert">
            <p>{error.message}</p>
            {error.hint ? <p className="hint">{error.hint}</p> : null}
          </div>
        ) : null}
        {loading && jobs.length === 0 ? (
          <p className="loading-line" role="status">
            正在读取任务…
          </p>
        ) : null}
        {!loading && jobs.length === 0 ? (
          <p className="muted">还没有核对或入库任务。回到核对台运行一次。</p>
        ) : null}
        {jobs.length > 0 ? (
          <div className="table-wrap responsive-wrap">
            <table className="data-table jobs-table">
              <thead>
                <tr>
                  <th>任务</th>
                  <th>创建时间</th>
                  <th>状态</th>
                  <th>阶段</th>
                  <th>进度</th>
                  <th>信息</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <td className="mono cell-job" data-label="任务">
                      <span className="tag">{job.kind === 'ingest' ? 'PDF 入库' : '核对'}</span>{' '}
                      {job.id}
                    </td>
                    <td className="cell-time" data-label="创建时间">
                      {formatTime(job.created_at)}
                    </td>
                    <td className="cell-status" data-label="状态">
                      <span className={`job-status job-${job.status}`}>
                        {JOB_LABELS[job.status] ?? job.status}
                      </span>
                    </td>
                    <td className="cell-stage" data-label="阶段">
                      {stageLabel(job.stage)}
                    </td>
                    <td className="cell-progress" data-label="进度">
                      {job.progress}%
                    </td>
                    <td className="job-message cell-message" data-label="信息">
                      {job.error ?? job.message}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  )
}
