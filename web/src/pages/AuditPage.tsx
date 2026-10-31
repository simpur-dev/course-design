import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ApiError, asApiError, getBibliographies, getDrafts, getJob, startAudit } from '../api'
import { ReportView } from '../components/ReportView'
import { stageLabel } from '../format'
import {
  isReportPayload,
  type AppConfig,
  type BibliographyFile,
  type DraftFile,
  type Job,
  type ReportPayload,
} from '../types'

const CITATION = /(\[@[^\]]+\])/g

function DraftPreview({ draft }: { draft: DraftFile }) {
  const lines = draft.content.split(/\r?\n/)
  const shown = lines.slice(0, 16)
  return (
    <div className="draft-preview">
      <div className="draft-preview-head">
        <span>草稿预览</span>
        <span className="muted small">
          {draft.line_count} 行 · {draft.char_count.toLocaleString('zh-CN')} 字符
        </span>
      </div>
      <div className="draft-lines">
        {shown.map((line, index) => (
          <div className="draft-line" key={index}>
            <span className="line-number">{index + 1}</span>
            <span className="line-text">
              {line.split(CITATION).map((part, partIndex) =>
                part.startsWith('[@') ? (
                  <span className="inline-citation" key={partIndex}>
                    {part}
                  </span>
                ) : (
                  part
                ),
              )}
            </span>
          </div>
        ))}
      </div>
      {draft.line_count > shown.length ? (
        <p className="muted small draft-more">仅展示前 {shown.length} 行</p>
      ) : null}
      {draft.truncated ? (
        <p className="muted small draft-more">预览只含前 20,000 字符；计数按完整草稿统计</p>
      ) : null}
    </div>
  )
}

export function AuditPage({ config, demo = false }: { config: AppConfig | null; demo?: boolean }) {
  const [drafts, setDrafts] = useState<DraftFile[]>([])
  const [bibliographies, setBibliographies] = useState<BibliographyFile[]>([])
  const [draftPath, setDraftPath] = useState('')
  const [bibPath, setBibPath] = useState('')
  const [paragraphs, setParagraphs] = useState(5)
  const [perLeg, setPerLeg] = useState(20)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<ApiError | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [report, setReport] = useState<ReportPayload | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([getDrafts(), getBibliographies()])
      .then(([draftPayload, bibPayload]) => {
        if (cancelled) {
          return
        }
        setDrafts(draftPayload.drafts)
        setBibliographies(bibPayload.bibliographies)
        setDraftPath((current) => current || draftPayload.drafts[0]?.path || '')
        setBibPath((current) => current || bibPayload.bibliographies[0]?.path || '')
        setLoading(false)
      })
      .catch((cause) => {
        if (!cancelled) {
          setLoadError(asApiError(cause))
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const jobId = job?.id
  const jobStatus = job?.status
  useEffect(() => {
    if (!jobId || (jobStatus !== 'queued' && jobStatus !== 'running')) {
      return
    }
    let cancelled = false
    const timer = window.setInterval(() => {
      getJob(jobId)
        .then((payload) => {
          if (cancelled) {
            return
          }
          setJob(payload.job)
          if (payload.job.status === 'succeeded' && isReportPayload(payload.job.result)) {
            setReport(payload.job.result)
          }
          if (payload.job.status === 'failed') {
            setError(new ApiError(payload.job.message, 0, payload.job.hint))
          }
        })
        .catch((cause) => {
          if (cancelled) {
            return
          }
          const apiError = asApiError(cause)
          if (apiError.status === 404) {
            setJob(null)
            setError(new ApiError('任务已不存在（服务可能已重启），请重新运行。', 404))
            return
          }
          setError(apiError)
        })
    }, 700)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [jobId, jobStatus])

  const selectedDraft = useMemo(
    () => drafts.find((draft) => draft.path === draftPath) ?? null,
    [drafts, draftPath],
  )
  const demoDraft = useMemo(
    () =>
      drafts.find((draft) => draft.path.replaceAll('\\', '/').endsWith('photon-demo.md')) ??
      null,
    [drafts],
  )
  const demoBib = useMemo(
    () => bibliographies.find((bib) => bib.path === 'samples/bib.json') ?? null,
    [bibliographies],
  )
  const demoReady = Boolean(demoDraft && demoBib)
  const running = jobStatus === 'queued' || jobStatus === 'running'
  const inputsReady = Boolean(draftPath && bibPath)
  const citationCount = selectedDraft?.citation_count ?? 0

  const runAreaRef = useRef<HTMLElement>(null)
  const autoDemo = useRef(false)

  function revealRunArea() {
    requestAnimationFrame(() => {
      runAreaRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  async function launch(draftValue: string, bibValue: string) {
    setError(null)
    setReport(null)
    setJob(null)
    revealRunArea()
    try {
      const payload = await startAudit({
        draft: draftValue,
        bib: bibValue,
        paragraphs,
        per_leg: perLeg,
      })
      setJob(payload.job)
    } catch (cause) {
      setError(asApiError(cause))
      revealRunArea()
    }
  }

  async function runDemo() {
    if (!demoDraft || !demoBib) {
      setError(
        new ApiError('示例文件缺失：需要 data/samples/photon-demo.md 与 data/samples/bib.json'),
      )
      return
    }
    setDraftPath(demoDraft.path)
    setBibPath(demoBib.path)
    await launch(demoDraft.path, demoBib.path)
  }

  useEffect(() => {
    if (!demo || loading || autoDemo.current || !demoDraft || !demoBib) {
      return
    }
    autoDemo.current = true
    setDraftPath(demoDraft.path)
    setBibPath(demoBib.path)
    void launch(demoDraft.path, demoBib.path)
    // launch reads the current retrieval settings; it must not retrigger on each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demo, loading, demoDraft, demoBib])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!draftPath || !bibPath) {
      setError(new ApiError('请选择草稿与论文库'))
      return
    }
    await launch(draftPath, bibPath)
  }

  return (
    <div className="audit-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Citation audit</p>
          <h1>核对台</h1>
          <p className="page-sub">
            导入草稿与论文库，逐条核对引用。每条候选只来自被引论文，结论必须落回原句与页码。
          </p>
        </div>
      </header>

      <section className={`demo-entry card ${demo ? 'is-active' : ''}`} aria-labelledby="demo-title">
        <div className="demo-copy">
          <p className="eyebrow">数据库顶会示例</p>
          <h2 id="demo-title">Photon · SIGMOD 2022</h2>
          <p className="muted small">
            5 条主张：4 条能在原文找到证据，1 条故意把 100TB 写成 500TB，用来展示不支持结论。
          </p>
        </div>
        <div className="demo-actions">
          <button
            type="button"
            className="button primary"
            onClick={runDemo}
            disabled={running || loading || !demoReady}
          >
            {running ? '示例运行中…' : '运行示例'}
          </button>
          <a className="text-link" href="#/papers">
            查看论文
          </a>
          {!demoReady && !loading ? (
            <span className="muted small">缺示例草稿或论文库</span>
          ) : null}
        </div>
      </section>

      <div className="workbench">
        <form className="setup card" onSubmit={onSubmit}>
          <div className="card-head">
            <h2>核对设置</h2>
            <span className="muted small">选择材料后运行</span>
          </div>

          {loadError ? (
            <div className="notice error">
              <strong>无法读取输入文件</strong>
              <p>{loadError.message}</p>
              {loadError.hint ? <p className="hint">{loadError.hint}</p> : null}
            </div>
          ) : null}

          <label className="field">
            <span>草稿</span>
            <select
              value={draftPath}
              onChange={(event) => setDraftPath(event.target.value)}
              disabled={loading || running}
            >
              {drafts.length === 0 ? <option value="">未发现 .md 草稿</option> : null}
              {drafts.map((draft) => (
                <option value={draft.path} key={draft.path}>
                  {draft.path}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>论文库</span>
            <select
              value={bibPath}
              onChange={(event) => setBibPath(event.target.value)}
              disabled={loading || running}
            >
              {bibliographies.length === 0 ? <option value="">未发现 .json 论文库</option> : null}
              {bibliographies.map((bib) => (
                <option value={bib.path} key={bib.path}>
                  {bib.path}
                </option>
              ))}
            </select>
          </label>

          <div className="run-action">
            {config?.baseline ? (
              <div className="notice baseline compact">
                <strong>无 key 基线</strong>
                <p>{config.baseline_notice}</p>
              </div>
            ) : null}
            <button
              type="submit"
              className="button primary run-button"
              disabled={running || loading || !inputsReady}
            >
              {running ? '核对中…' : '开始核对'}
            </button>
            {!loading && !inputsReady ? (
              <p className="muted small">先准备至少一份 Markdown 草稿与一个 JSON 论文库。</p>
            ) : (
              <p className="muted small">
                结果写入 <span className="mono">data/runtime/reports/</span>，同时提供 Markdown、CSV、JSON。
              </p>
            )}
          </div>

          {selectedDraft ? <DraftPreview draft={selectedDraft} /> : null}

          <div className="setup-stats">
            <div>
              <span className="stat-value">{citationCount}</span>
              <span className="stat-label">引用标记</span>
            </div>
            <div>
              <span className="stat-value">{drafts.length}</span>
              <span className="stat-label">可选草稿</span>
            </div>
            <div>
              <span className="stat-value">{bibliographies.length}</span>
              <span className="stat-label">可选论文库</span>
            </div>
          </div>

          <details className="advanced">
            <summary>检索参数</summary>
            <div className="advanced-grid">
              <label className="field">
                <span>段落候选数</span>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={paragraphs}
                  disabled={running}
                  onChange={(event) => setParagraphs(Number(event.target.value) || 1)}
                />
              </label>
              <label className="field">
                <span>每路检索候选数</span>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={perLeg}
                  disabled={running}
                  onChange={(event) => setPerLeg(Number(event.target.value) || 1)}
                />
              </label>
            </div>
            <p className="muted small">
              段落优先：先取段落候选，再在段落内选择最支持主张的句子。全文检索与向量检索各取这么多条候选，两路都限定在被引论文内。
            </p>
          </details>
        </form>

        <section className="run-area" ref={runAreaRef} aria-labelledby="run-area-title">
          <div className="card-head">
            <h2 id="run-area-title">核对结果</h2>
            <span className="muted small">逐条可审计</span>
          </div>

          {error ? (
            <div className="notice error" role="alert">
              <strong>{error.status === 409 ? '已有任务运行' : '核对未完成'}</strong>
              <p>{error.message}</p>
              {error.hint ? <p className="hint">{error.hint}</p> : null}
            </div>
          ) : null}

          {job && running ? (
            <section className="progress-card card" aria-live="polite">
              <div className="progress-head">
                <div>
                  <p className="eyebrow">{stageLabel(job.stage)}</p>
                  <h3>{job.message || '正在准备'}</h3>
                </div>
                <span className="progress-value mono">{job.progress}%</span>
              </div>
              <div
                className="progress-track"
                role="progressbar"
                aria-label="核对进度"
                aria-valuenow={job.progress}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <div className="progress-fill" style={{ width: `${job.progress}%` }} />
              </div>
              <p className="muted small">
                任务 {job.id}
                {job.claim_id ? ` · 当前 ${job.claim_id}` : ''} ·
                证据只在被引论文内检索，请保持页面打开。
              </p>
            </section>
          ) : null}

          {report ? (
            <>
              <div className="notice success run-summary" role="status">
                <strong>核对完成</strong>
                <p>
                  共 {report.summary.claims} 条主张 / {report.summary.citations} 条引用；
                  需人工复核 {report.summary.review_required} 条。
                </p>
                <div className="download-row">
                  <a className="button ghost" href={report.downloads?.markdown} download>
                    Markdown
                  </a>
                  <a className="button ghost" href={report.downloads?.csv} download>
                    CSV
                  </a>
                  <a className="button ghost" href={report.downloads?.json} download>
                    JSON
                  </a>
                  <a className="button ghost" href={`#/reports/${report.run_id}`}>
                    独立报告页
                  </a>
                </div>
              </div>
              <ReportView key={report.run_id} report={report} />
            </>
          ) : null}

          {!report && !running && !error ? (
            <section className="empty-state card">
              <div className="empty-mark" aria-hidden="true">
                引
              </div>
              <h3>尚未运行核对</h3>
              <p>
                确认草稿与论文库后开始核对。每一条结论都会附带原文、页码、检索参数与
                RRF 排序，可逐条展开审计。
              </p>
              <ol className="flow-list">
                <li>解析草稿中的 [@key] 引用</li>
                <li>在被引论文内做全文 + 向量混合检索</li>
                <li>段落优先选证据，输出四档结论</li>
                <li>导出报告并保留检索记录</li>
              </ol>
            </section>
          ) : null}
        </section>
      </div>
    </div>
  )
}
