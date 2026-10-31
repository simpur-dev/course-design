import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import {
  VERDICT_LABELS,
  cleanReason,
  confidenceLabel,
  formatLineRange,
  formatPercent,
  formatSeconds,
  numberStatusLabel,
} from '../../../shared/format'
import type { CitationCheck, ClaimResult } from '../../../shared/types'
import { VerdictBadge } from './VerdictBadge'

function rank(value: number | null): string {
  return value === null ? '—' : String(value)
}

export function EvidenceDrawer({
  claim,
  check,
  downloads,
  onClose,
}: {
  claim: ClaimResult
  check: CitationCheck
  downloads?: Record<string, string>
  onClose: () => void
}) {
  const panelRef = useRef<HTMLElement>(null)
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    onCloseRef.current = onClose
  })

  useEffect(() => {
    const previousFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previousOverflow = document.body.style.overflow
    panelRef.current?.querySelector<HTMLElement>('[data-drawer-close]')?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab') {
        return
      }
      const panel = panelRef.current
      if (!panel) {
        return
      }
      const focusable = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.offsetParent !== null)
      if (focusable.length === 0) {
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
      previousFocus?.focus()
    }
  }, [])

  const evidence = check.evidence

  return createPortal(
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        ref={panelRef}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="drawer-head">
          <div>
            <p className="eyebrow">检索审计 · {check.citation}</p>
            <h2 id="drawer-title">证据与检索路径</h2>
          </div>
          <button
            type="button"
            className="icon-button"
            data-drawer-close
            onClick={onClose}
          >
            关闭
          </button>
        </header>

        <div className="drawer-body">
          <section className="drawer-section">
            <h3>主张</h3>
            <blockquote className="claim-blockquote">{claim.text}</blockquote>
            <p className="muted">
              {claim.claim_id} · {formatLineRange(claim.line_start, claim.line_end)} ·
              {claim.citations.map((key) => ` @${key}`).join('')}
            </p>
          </section>

          <section className="drawer-section">
            <h3>引用归属</h3>
            <div className="attribution">
              <span className="mono">@{check.citation}</span>
              <div>
                <strong>{check.paper.title || check.paper.paper_key}</strong>
                <p className="muted">
                  {check.paper.authors}
                  {check.paper.year ? ` · ${check.paper.year}` : ''}
                </p>
              </div>
            </div>
            <p className="boundary-note">
              检索边界：本次候选只来自 <span className="mono">{check.paper.paper_key}</span>，
              不会借用其他论文的句子。
            </p>
          </section>

          <section className="drawer-section">
            <div className="section-title-row">
              <h3>判定</h3>
              <VerdictBadge verdict={check.verdict} />
            </div>
            <p className="reason">{cleanReason(check.reason)}</p>
            <dl className="metric-grid">
              <div>
                <dt>置信度</dt>
                <dd>{confidenceLabel(check.confidence)}</dd>
              </div>
              <div>
                <dt>人工复核</dt>
                <dd>{check.review_required ? '需要' : '不需要'}</dd>
              </div>
              <div>
                <dt>数字状态</dt>
                <dd>{numberStatusLabel(check.number_status)}</dd>
              </div>
              <div>
                <dt>耗时</dt>
                <dd>{formatSeconds(check.seconds)}</dd>
              </div>
            </dl>
            {check.error ? <p className="error-line">错误：{check.error}</p> : null}
          </section>

          <section className="drawer-section">
            <h3>原文证据</h3>
            {evidence ? (
              <>
                <div className="evidence-meta">
                  <span>第 {evidence.page} 页</span>
                  <span className="mono">{evidence.unit_id}</span>
                  <span>{evidence.unit_type === 'sent' ? '句' : '段'}</span>
                </div>
                <blockquote className="evidence-quote">{evidence.text}</blockquote>
                <dl className="metric-grid metric-grid-4">
                  <div>
                    <dt>综合分</dt>
                    <dd>{evidence.score.toFixed(3)}</dd>
                  </div>
                  <div>
                    <dt>余弦</dt>
                    <dd>{evidence.cosine.toFixed(3)}</dd>
                  </div>
                  <div>
                    <dt>关键词覆盖</dt>
                    <dd>{formatPercent(evidence.keyword_coverage)}</dd>
                  </div>
                  <div>
                    <dt>数字</dt>
                    <dd>{numberStatusLabel(evidence.number_status)}</dd>
                  </div>
                </dl>
              </>
            ) : (
              <p className="muted">本次没有返回可用证据，判定为
                {VERDICT_LABELS[check.verdict] ?? check.verdict}。</p>
            )}
            <div className="keyword-row">
              <span className="muted">检索关键词</span>
              {check.keywords.length === 0 ? (
                <span className="muted">（未抽取到英文关键词）</span>
              ) : (
                check.keywords.map((keyword) => (
                  <span className="keyword" key={keyword}>
                    {keyword}
                  </span>
                ))
              )}
            </div>
          </section>

          <section className="drawer-section">
            <h3>段落检索（先取段落）</h3>
            {check.paragraph_hits.length === 0 ? (
              <p className="muted">没有段落候选。</p>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>段落 id</th>
                      <th>页</th>
                      <th>RRF</th>
                      <th>全文排名</th>
                      <th>向量排名</th>
                    </tr>
                  </thead>
                  <tbody>
                    {check.paragraph_hits.map((hit, index) => (
                      <tr key={hit.unit_id}>
                        <td>{index + 1}</td>
                        <td className="mono">{hit.unit_id}</td>
                        <td>{hit.page}</td>
                        <td>{hit.rrf_score.toFixed(4)}</td>
                        <td>{rank(hit.fulltext_rank)}</td>
                        <td>{rank(hit.vector_rank)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="drawer-section">
            <h3>句内候选（再选证据）</h3>
            {check.sentence_candidates.length === 0 ? (
              <p className="muted">没有句级候选。</p>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>句子 id</th>
                      <th>页</th>
                      <th>综合分</th>
                      <th>余弦</th>
                      <th>覆盖</th>
                      <th>数字</th>
                    </tr>
                  </thead>
                  <tbody>
                    {check.sentence_candidates.map((candidate, index) => (
                      <tr
                        key={candidate.unit_id}
                        className={candidate.unit_id === evidence?.unit_id ? 'selected-row' : ''}
                      >
                        <td>{index + 1}</td>
                        <td className="mono">{candidate.unit_id}</td>
                        <td>{candidate.page}</td>
                        <td>{candidate.score.toFixed(3)}</td>
                        <td>{candidate.cosine.toFixed(3)}</td>
                        <td>{formatPercent(candidate.keyword_coverage)}</td>
                        <td>{numberStatusLabel(candidate.number_status)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {downloads ? (
            <section className="drawer-section drawer-downloads">
              <h3>导出本次报告</h3>
              <div className="download-row">
                <a className="button ghost" href={downloads.markdown} download>
                  Markdown
                </a>
                <a className="button ghost" href={downloads.csv} download>
                  CSV
                </a>
                <a className="button ghost" href={downloads.json} download>
                  JSON
                </a>
              </div>
            </section>
          ) : null}
        </div>
      </aside>
    </div>,
    document.body,
  )
}
