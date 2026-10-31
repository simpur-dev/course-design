import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError, asApiError, getJob, getPapers, uploadPdf } from '../../shared/api'
import { formatNumber, formatTime } from '../../shared/format'
import {
  isIngestResult,
  type IngestResult,
  type Job,
  type PaperRecord,
  type UploadedPaper,
} from '../../shared/types'

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024

function formatBytes(value: number): string {
  if (value >= 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MB`
  }
  return `${Math.max(1, Math.round(value / 1024))} KB`
}

export function PapersPage() {
  const [papers, setPapers] = useState<PaperRecord[]>([])
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<ApiError | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [authors, setAuthors] = useState('')
  const [year, setYear] = useState('')
  const [uploadJob, setUploadJob] = useState<Job | null>(null)
  const [uploadedPaper, setUploadedPaper] = useState<UploadedPaper | null>(null)
  const [duplicate, setDuplicate] = useState(false)
  const [uploadError, setUploadError] = useState<ApiError | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let cancelled = false
    getPapers()
      .then((payload) => {
        if (cancelled) {
          return
        }
        setPapers(payload.papers)
        setStatus('ready')
        setError(null)
      })
      .catch((cause) => {
        if (cancelled) {
          return
        }
        setError(asApiError(cause))
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [reloadToken])

  const jobId = uploadJob?.id
  const jobStatus = uploadJob?.status
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
          setUploadJob(payload.job)
          if (payload.job.status === 'succeeded') {
            setReloadToken((value) => value + 1)
          }
          if (payload.job.status === 'failed') {
            setUploadError(new ApiError(payload.job.message, 0, payload.job.hint))
          }
        })
        .catch((cause) => {
          if (cancelled) {
            return
          }
          const apiError = asApiError(cause)
          if (apiError.status === 404) {
            setUploadJob(null)
            setUploadError(
              new ApiError('入库任务已不存在（服务可能已重启），请刷新论文库或重新上传。', 404),
            )
            setReloadToken((value) => value + 1)
            return
          }
          setUploadError(apiError)
        })
    }, 800)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [jobId, jobStatus])

  const running = jobStatus === 'queued' || jobStatus === 'running'
  const ingestResult: IngestResult | null =
    uploadJob?.kind === 'ingest' && isIngestResult(uploadJob.result) ? uploadJob.result : null

  const paragraphs = papers.reduce((sum, paper) => sum + paper.para_count, 0)
  const sentences = papers.reduce((sum, paper) => sum + paper.sent_count, 0)

  function refreshLibrary() {
    setStatus('loading')
    setReloadToken((value) => value + 1)
  }

  function resetUpload() {
    setFile(null)
    setTitle('')
    setAuthors('')
    setYear('')
    if (fileInput.current) {
      fileInput.current.value = ''
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setUploadError(null)
    if (!file) {
      setUploadError(new ApiError('请先选择一个 PDF 文件'))
      return
    }
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setUploadError(new ApiError('只支持 PDF 文件'))
      return
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setUploadError(new ApiError('PDF 不能超过 25 MB', 413, '请压缩或拆分 PDF 后再上传'))
      return
    }
    let parsedYear: number | null = null
    if (year.trim()) {
      parsedYear = Number(year)
      if (!Number.isInteger(parsedYear) || parsedYear < 1000 || parsedYear > 3000) {
        setUploadError(new ApiError('年份需在 1000 到 3000 之间'))
        return
      }
    }
    setUploadJob(null)
    setUploadedPaper(null)
    setDuplicate(false)
    try {
      const payload = await uploadPdf(file, { title, authors, year: parsedYear })
      setUploadJob(payload.job)
      setUploadedPaper(payload.paper)
      setDuplicate(payload.duplicate)
      resetUpload()
    } catch (cause) {
      setUploadError(asApiError(cause))
    }
  }

  return (
    <div className="papers-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Evidence library</p>
          <h1>论文库</h1>
          <p className="page-sub">
            已入库的论文与证据单元。核对时只会检索被引论文内部的段落与句子，页码可回溯。
          </p>
        </div>
        <button
          type="button"
          className="button ghost"
          onClick={refreshLibrary}
          disabled={status === 'loading'}
        >
          {status === 'loading' ? '刷新中…' : '刷新'}
        </button>
      </header>

      {status === 'error' && error ? (
        <div className="notice error" role="alert">
          <strong>无法读取论文库</strong>
          <p>{error.message}</p>
          {error.hint ? <p className="hint">{error.hint}</p> : null}
          <button
            type="button"
            className="button ghost small-button notice-action"
            onClick={refreshLibrary}
          >
            重试
          </button>
        </div>
      ) : null}

      <section className="card upload-card" aria-labelledby="upload-title">
        <div className="card-head">
          <div>
            <h2 id="upload-title">上传 PDF 入库</h2>
            <p className="muted small">
              支持 25 MB 以内的 PDF。入库完成后会自动刷新论文库，也可以离开，稍后再回来。
            </p>
          </div>
          <span className="muted small">最多 25 MB</span>
        </div>

        <form className="upload-form" onSubmit={onSubmit} noValidate>
          <div className="file-field">
            <span className="file-label" id="upload-file-label">
              PDF 文件
            </span>
            <div className={`file-picker${file ? ' has-file' : ''}${running ? ' is-disabled' : ''}`}>
              <input
                ref={fileInput}
                className="file-picker-input"
                type="file"
                accept=".pdf,application/pdf"
                disabled={running}
                aria-labelledby="upload-file-label"
                aria-describedby="upload-file-hint"
                onChange={(event) => {
                  setFile(event.target.files?.[0] ?? null)
                  setUploadError(null)
                }}
              />
              <span className="file-picker-mark" aria-hidden="true">
                PDF
              </span>
              <span className="file-picker-copy">
                <strong>{file ? file.name : '选择本地 PDF'}</strong>
                <span id="upload-file-hint" className="muted small">
                  {file
                    ? `${formatBytes(file.size)} · 点击可更换文件`
                    : '点击选择会议论文或其他 PDF 文件'}
                </span>
              </span>
              <span className="button ghost small-button file-picker-action" aria-hidden="true">
                {file ? '重新选择' : '选择文件'}
              </span>
            </div>
          </div>

          <details className="upload-extra">
            <summary>
              <span>补充论文信息（可选）</span>
              <span className="muted small upload-extra-hint">不填也能入库，标题默认使用文件名</span>
            </summary>
            <div className="upload-meta">
              <label className="field">
                <span>标题</span>
                <input
                  type="text"
                  value={title}
                  maxLength={300}
                  disabled={running}
                  placeholder="默认使用文件名"
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
              <label className="field">
                <span>作者</span>
                <input
                  type="text"
                  value={authors}
                  maxLength={300}
                  disabled={running}
                  placeholder="例如 Alexander Behm et al."
                  onChange={(event) => setAuthors(event.target.value)}
                />
              </label>
              <label className="field field-year">
                <span>年份</span>
                <input
                  type="number"
                  min={1000}
                  max={3000}
                  value={year}
                  disabled={running}
                  placeholder="2022"
                  onChange={(event) => setYear(event.target.value)}
                />
              </label>
            </div>
          </details>

          <div className="upload-actions">
            <button type="submit" className="button primary" disabled={running || !file}>
              {running ? '入库中…' : '上传并入库'}
            </button>
            {file ? (
              <button
                type="button"
                className="button ghost"
                disabled={running}
                onClick={resetUpload}
              >
                清除
              </button>
            ) : null}
          </div>
        </form>

        {uploadError ? (
          <div className="notice error" role="alert">
            <strong>{uploadError.status === 409 ? '无法开始入库' : '上传未完成'}</strong>
            <p>{uploadError.message}</p>
            {uploadError.hint ? <p className="hint">{uploadError.hint}</p> : null}
          </div>
        ) : null}

        {uploadJob && running ? (
          <div className="upload-status" aria-live="polite">
            <div className="upload-status-head">
              <div>
                <p className="eyebrow">PDF 入库</p>
                <h3>{uploadJob.message || '正在准备'}</h3>
              </div>
              <span className="mono">{uploadJob.progress}%</span>
            </div>
            <div
              className="progress-track"
              role="progressbar"
              aria-label="入库进度"
              aria-valuenow={uploadJob.progress}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div className="progress-fill" style={{ width: `${uploadJob.progress}%` }} />
            </div>
            <p className="muted small">任务 {uploadJob.id} · 论文 key 会写入 data/uploads/bib.json</p>
          </div>
        ) : null}

        {uploadJob?.status === 'succeeded' && uploadedPaper ? (
          <div className="notice success" role="status">
            <strong>{duplicate ? '该 PDF 已在库中，已重新校验入库' : 'PDF 已入库'}</strong>
            <p>
              论文 key <code className="mono">{uploadedPaper.key}</code>；在草稿中写{' '}
              <code className="mono">[@{uploadedPaper.key}]</code> 即可引用。
            </p>
            {ingestResult ? (
              <p className="muted small">
                {ingestResult.status === 'skipped' ? '内容未变化，已跳过重复向量化；' : ''}
                {ingestResult.page_count} 页 · {formatNumber(ingestResult.para_count)} 段落 ·{' '}
                {formatNumber(ingestResult.sent_count)} 句子
                {ingestResult.seconds ? ` · ${ingestResult.seconds.toFixed(1)} 秒` : ''}
              </p>
            ) : null}
            <button
              type="button"
              className="text-link text-button"
              onClick={() => {
                const library = document.getElementById('library')
                library?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                library?.focus({ preventScroll: true })
              }}
            >
              查看论文库
            </button>
          </div>
        ) : null}
      </section>

      {status === 'ready' ? (
        <>
          <section className="library-stats" id="library" tabIndex={-1}>
            <div className="stat-card card">
              <span className="stat-value">{papers.length}</span>
              <span className="stat-label">论文</span>
            </div>
            <div className="stat-card card">
              <span className="stat-value">{formatNumber(paragraphs)}</span>
              <span className="stat-label">段落单元</span>
            </div>
            <div className="stat-card card">
              <span className="stat-value">{formatNumber(sentences)}</span>
              <span className="stat-label">句子单元</span>
            </div>
          </section>

          {papers.length === 0 ? (
            <section className="empty-state card">
              <div className="empty-mark" aria-hidden="true">
                据
              </div>
              <h3>论文库为空</h3>
              <p>先上传一个 PDF，或在终端运行样例入库：</p>
              <pre className="code-block">citationproof ingest --bib data/samples/bib.json</pre>
            </section>
          ) : (
            <div className="paper-grid">
              {papers.map((paper) => (
                <article className="paper-card card" key={paper.paper_key}>
                  <div className="paper-top">
                    <span className="citation-chip mono">{paper.paper_key}</span>
                    <span className="paper-top-meta">
                      {paper.paper_key === 'behm2022' ? (
                        <span className="tag demo-tag">示例</span>
                      ) : null}
                      <span className="muted small">{paper.year ?? '—'}</span>
                    </span>
                  </div>
                  <h2>{paper.title || paper.paper_key}</h2>
                  <p className="paper-authors">{paper.authors || '—'}</p>
                  <dl className="paper-stats">
                    <div>
                      <dt>页数</dt>
                      <dd>{paper.page_count}</dd>
                    </div>
                    <div>
                      <dt>段落</dt>
                      <dd>{formatNumber(paper.para_count)}</dd>
                    </div>
                    <div>
                      <dt>句子</dt>
                      <dd>{formatNumber(paper.sent_count)}</dd>
                    </div>
                  </dl>
                  <p className="muted small paper-file mono" title={paper.file_name}>
                    {paper.file_name}
                  </p>
                  <div className="paper-foot">
                    <span className="muted small">入库于 {formatTime(paper.ingested_at)}</span>
                    <span className="paper-links">
                      {paper.paper_key === 'behm2022' ? (
                        <a className="text-link" href="#/audit/demo">
                          核对示例
                        </a>
                      ) : null}
                      {paper.source_url ? (
                        <a
                          className="text-link"
                          href={paper.source_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          来源
                        </a>
                      ) : null}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </>
      ) : null}

      {status === 'loading' ? (
        <p className="loading-line" role="status">
          正在读取论文库…
        </p>
      ) : null}
    </div>
  )
}
