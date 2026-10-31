import { useEffect, useState } from 'react'
import { asApiError, getReport, type ApiError } from '../api'
import { ReportView } from '../components/ReportView'
import type { ReportPayload } from '../types'

export function ReportDetailPage({ runId }: { runId: string }) {
  const [report, setReport] = useState<ReportPayload | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    let cancelled = false
    getReport(runId)
      .then((payload) => {
        if (!cancelled) {
          setReport(payload)
        }
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(asApiError(cause))
        }
      })
    return () => {
      cancelled = true
    }
  }, [runId, reloadToken])

  return (
    <div className="report-detail-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Report detail</p>
          <h1>报告详情</h1>
          <p className="page-sub mono">{runId}</p>
        </div>
        <a className="button ghost" href="#/reports">
          返回报告列表
        </a>
      </header>

      {error ? (
        <div className="notice error" role="alert">
          <strong>无法打开报告</strong>
          <p>{error.message}</p>
          {error.hint ? <p className="hint">{error.hint}</p> : null}
          <div className="download-row notice-action">
            <button
              type="button"
              className="button ghost"
              onClick={() => {
                setReport(null)
                setError(null)
                setReloadToken((value) => value + 1)
              }}
            >
              重试
            </button>
            <a className="button ghost" href="#/reports">
              返回列表
            </a>
          </div>
        </div>
      ) : null}

      {report === null && error === null ? (
        <p className="loading-line" role="status">
          正在读取报告…
        </p>
      ) : null}
      {report ? <ReportView key={report.run_id} report={report} /> : null}
    </div>
  )
}
