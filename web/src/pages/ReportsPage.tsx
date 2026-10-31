import { useEffect, useState } from 'react'
import { asApiError, getReports, type ApiError } from '../api'
import { VERDICT_LABELS, basename, formatTime } from '../format'
import type { ReportListItem, Verdict } from '../types'

const VERDICT_ORDER: Verdict[] = ['supported', 'partial', 'unsupported', 'unknown']

export function ReportsPage() {
  const [reports, setReports] = useState<ReportListItem[]>([])
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<ApiError | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    let cancelled = false
    getReports()
      .then((payload) => {
        if (cancelled) {
          return
        }
        setReports(payload.reports)
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

  return (
    <div className="reports-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Audit reports</p>
          <h1>核对报告</h1>
          <p className="page-sub">
            每次核对都会留下 Markdown、CSV 与 JSON 三份记录；报告中的每条结论都能反查到证据 id。
          </p>
        </div>
        <button
          type="button"
          className="button ghost"
          disabled={status === 'loading'}
          onClick={() => {
            setStatus('loading')
            setReloadToken((value) => value + 1)
          }}
        >
          {status === 'loading' ? '刷新中…' : '刷新'}
        </button>
      </header>

      {status === 'error' && error ? (
        <div className="notice error" role="alert">
          <strong>无法读取报告</strong>
          <p>{error.message}</p>
          {error.hint ? <p className="hint">{error.hint}</p> : null}
          <button
            type="button"
            className="button ghost small-button notice-action"
            onClick={() => {
              setStatus('loading')
              setReloadToken((value) => value + 1)
            }}
          >
            重试
          </button>
        </div>
      ) : null}

      {status === 'loading' ? (
        <p className="loading-line" role="status">
          正在读取报告目录…
        </p>
      ) : null}

      {status === 'ready' && reports.length === 0 ? (
        <section className="empty-state card">
          <div className="empty-mark" aria-hidden="true">
            报
          </div>
          <h3>还没有核对报告</h3>
          <p>回到核对台运行一次核对，或使用命令行生成：</p>
          <pre className="code-block">
            yinju audit --draft data/samples/draft.md --bib data/samples/bib.json
          </pre>
          <a className="button primary" href="#/">
            前往核对台
          </a>
        </section>
      ) : null}

      {status === 'ready' && reports.length > 0 ? (
        <section className="card report-table-card">
          <div className="card-head reports-head">
            <h2>全部报告</h2>
            <span className="muted small">
              共 {reports.length} 份 · 最新 {formatTime(reports[0].generated_at)}
            </span>
          </div>
          <div className="table-wrap responsive-wrap">
            <table className="data-table reports-table">
              <thead>
                <tr>
                  <th>生成时间</th>
                  <th>草稿</th>
                  <th>判定器</th>
                  <th>主张 / 引用</th>
                  <th>结论分布</th>
                  <th>复核</th>
                  <th>导出</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {reports.map((report, index) => (
                  <tr key={report.run_id}>
                    <td className="cell-time" data-label="生成时间">
                      <div className="time-line">
                        <span>{formatTime(report.generated_at)}</span>
                        {index === 0 ? <span className="tag latest-tag">最新</span> : null}
                      </div>
                      <div className="mono muted small">{report.run_id}</div>
                    </td>
                    <td className="cell-draft" data-label="草稿" title={report.draft}>
                      {basename(report.draft)}
                      {report.draft?.replaceAll('\\', '/').endsWith('photon-demo.md') ? (
                        <span className="tag demo-tag">示例</span>
                      ) : null}
                    </td>
                    <td className="cell-verifier mono" data-label="判定器">
                      {report.verifier}
                    </td>
                    <td className="cell-count" data-label="主张 / 引用">
                      {report.summary.claims} / {report.summary.citations}
                    </td>
                    <td className="cell-verdicts" data-label="结论分布">
                      <div className="verdict-inline">
                        {VERDICT_ORDER.map((verdict) => (
                          <span className={`mini-count mini-${verdict}`} key={verdict}>
                            {VERDICT_LABELS[verdict]} {report.summary.claim_verdicts[verdict] ?? 0}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="cell-review" data-label="需复核">
                      {report.summary.review_required}
                    </td>
                    <td className="cell-exports" data-label="导出">
                      <div className="download-row compact">
                        <a
                          className="text-link"
                          href={report.downloads.markdown}
                          download
                          aria-label={`下载 ${formatTime(report.generated_at)} 报告的 Markdown`}
                        >
                          MD
                        </a>
                        <a
                          className="text-link"
                          href={report.downloads.csv}
                          download
                          aria-label={`下载 ${formatTime(report.generated_at)} 报告的 CSV`}
                        >
                          CSV
                        </a>
                        <a
                          className="text-link"
                          href={report.downloads.json}
                          download
                          aria-label={`下载 ${formatTime(report.generated_at)} 报告的 JSON`}
                        >
                          JSON
                        </a>
                      </div>
                    </td>
                    <td className="cell-open">
                      <a
                        className="button ghost small-button"
                        href={`#/reports/${report.run_id}`}
                        aria-label={`打开 ${formatTime(report.generated_at)} 的报告`}
                      >
                        打开
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  )
}
