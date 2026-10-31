import { useState } from 'react'
import {
  VERDICT_LABELS,
  basename,
  cleanReason,
  confidenceLabel,
  formatLineRange,
  formatPercent,
  formatSeconds,
  formatTime,
  numberStatusLabel,
} from '../../../shared/format'
import type { CitationCheck, ClaimResult, MemorySync, ReportPayload, Verdict } from '../../../shared/types'
import { EvidenceDrawer } from './EvidenceDrawer'
import { VerdictBadge } from './VerdictBadge'

const VERDICT_ORDER: Verdict[] = ['supported', 'partial', 'unsupported', 'unknown']

function modelLabel(value: string): string {
  const parts = value.split('|').filter(Boolean)
  if (parts.length > 1 && parts[0] === 'default') {
    return parts.slice(1).join(' · ')
  }
  return parts.join(' · ') || '—'
}

function MemoryStrip({ memory }: { memory: MemorySync }) {
  const revision = memory.handoff?.current_revision?.revision ?? memory.handoff?.revision ?? null
  const state = !memory.enabled ? 'off' : memory.ok ? 'ok' : 'bad'
  const label = !memory.enabled ? '记忆写入已关闭' : memory.ok ? '已写入项目记忆' : '记忆未写入'

  return (
    <section className={`memory-strip card memory-strip-${state}`}>
      <div className="memory-strip-main">
        <div className="memory-strip-head">
          <span className={`status-pill ${state === 'ok' ? 'ok' : state === 'bad' ? 'bad' : 'wait'}`}>
            {label}
          </span>
          {memory.project ? <strong className="mono">{memory.project}</strong> : null}
        </div>
        {memory.ok ? (
          <p className="muted small">
            写入 {memory.written} 条 · 去重跳过 {memory.skipped} 条 ·{' '}
            {revision !== null ? `交接 r${revision}` : '本次未生成交接'}
          </p>
        ) : null}
        {!memory.enabled ? (
          <p className="muted small">
            设置 APP_MEMORY_ENABLED=true 后，核对会把判断、下一步与交接写入 PowerContext。
          </p>
        ) : null}
        {memory.enabled && !memory.ok ? (
          <p className="error-line">
            记忆未写入：{memory.error ?? '未知错误'}
            {memory.hint ? ` · ${memory.hint}` : ''}
          </p>
        ) : null}
      </div>
      {memory.project ? (
        <a
          className="button ghost small-button"
          href={`#/memory?project=${encodeURIComponent(memory.project)}`}
        >
          查看项目记忆
        </a>
      ) : null}
    </section>
  )
}

function VerdictCounts({ counts }: { counts: Record<Verdict, number> }) {
  return (
    <div className="verdict-counts">
      {VERDICT_ORDER.map((verdict) => (
        <div className={`verdict-count verdict-count-${verdict}`} key={verdict}>
          <span className="count-value">{counts[verdict] ?? 0}</span>
          <span className="count-label">{VERDICT_LABELS[verdict]}</span>
        </div>
      ))}
    </div>
  )
}

export function ReportView({ report }: { report: ReportPayload }) {
  const [active, setActive] = useState<{ claim: ClaimResult; check: CitationCheck } | null>(null)
  const [verdictFilter, setVerdictFilter] = useState<Verdict | 'all'>('all')
  const [reviewOnly, setReviewOnly] = useState(false)
  const baseline = report.verifier.startsWith('none')
  const baselineWarningShown = report.warnings.some((warning) => warning.includes('verifier=none'))
  const needsReview = (claim: ClaimResult) =>
    claim.checks.some((check) => check.review_required)
  const inVerdict = (claim: ClaimResult) =>
    verdictFilter === 'all' || claim.verdict === verdictFilter
  const reviewInScope = report.claims.filter(
    (claim) => inVerdict(claim) && needsReview(claim),
  ).length
  const filteredClaims = report.claims.filter(
    (claim) => inVerdict(claim) && (!reviewOnly || needsReview(claim)),
  )

  return (
    <div className="report-view">
      <section className="report-meta card">
        <div className="report-meta-main">
          <div>
            <p className="eyebrow">核对批次</p>
            <h2 className="run-id mono">{report.run_id}</h2>
            <p className="muted">生成于 {formatTime(report.generated_at)}</p>
          </div>
          <VerdictCounts counts={report.summary.claim_verdicts} />
        </div>
        {report.summary.claims > 0 ? (
          <div className="verdict-bar" aria-hidden="true">
            {VERDICT_ORDER.map((verdict) => {
              const count = report.summary.claim_verdicts[verdict] ?? 0
              return count > 0 ? (
                <span
                  key={verdict}
                  className={`verdict-bar-${verdict}`}
                  style={{ flexGrow: count }}
                />
              ) : null
            })}
          </div>
        ) : null}
        <dl className="meta-list">
          <div>
            <dt>草稿</dt>
            <dd title={report.draft}>{basename(report.draft)}</dd>
          </div>
          <div>
            <dt>论文库</dt>
            <dd title={report.bib}>{basename(report.bib)}</dd>
          </div>
          <div>
            <dt>判定器</dt>
            <dd className="mono">{report.verifier}</dd>
          </div>
          <div>
            <dt>向量模型</dt>
            <dd className="mono" title={report.embedding_model}>
              {modelLabel(report.embedding_model)}
            </dd>
          </div>
          <div>
            <dt>主张 / 引用</dt>
            <dd>
              {report.summary.claims} / {report.summary.citations}
            </dd>
          </div>
          <div>
            <dt>需人工复核</dt>
            <dd>{report.summary.review_required}</dd>
          </div>
        </dl>
        <p className="muted small">
          引用结论：
          {VERDICT_ORDER.map(
            (verdict) => `${VERDICT_LABELS[verdict]} ${report.summary.citation_verdicts[verdict] ?? 0}`,
          ).join(' · ')}
          {report.summary.errors > 0 ? ` · 错误 ${report.summary.errors}` : ''}
        </p>
        {baseline && !baselineWarningShown ? (
          <p className="baseline-inline">
            当前为无 key 基线：不会出具「支持」；「部分支持」表示证据高度相关但仍需人工确认。
          </p>
        ) : null}
        {report.downloads ? (
          <div className="download-row">
            <a className="button ghost" href={report.downloads.markdown} download>
              导出 Markdown
            </a>
            <a className="button ghost" href={report.downloads.csv} download>
              导出 CSV
            </a>
            <a className="button ghost" href={report.downloads.json} download>
              导出 JSON
            </a>
          </div>
        ) : null}
      </section>

      {report.memory ? <MemoryStrip memory={report.memory} /> : null}

      {report.warnings.length > 0 ? (
        <section className="warnings">
          {report.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </section>
      ) : null}

      <div className="claim-filters" role="group" aria-label="筛选主张">
        <span className="filter-label">筛选</span>
        <button
          type="button"
          className={`filter-chip${verdictFilter === 'all' ? ' active' : ''}`}
          aria-pressed={verdictFilter === 'all'}
          onClick={() => setVerdictFilter('all')}
        >
          全部 {report.claims.length}
        </button>
        {VERDICT_ORDER.map((verdict) => (
          <button
            type="button"
            className={`filter-chip${verdictFilter === verdict ? ' active' : ''}`}
            aria-pressed={verdictFilter === verdict}
            key={verdict}
            onClick={() => setVerdictFilter(verdict)}
          >
            {VERDICT_LABELS[verdict]} {report.summary.claim_verdicts[verdict] ?? 0}
          </button>
        ))}
        <span className="filter-divider" aria-hidden="true" />
        <button
          type="button"
          className={`filter-chip review-chip${reviewOnly ? ' active' : ''}`}
          aria-pressed={reviewOnly}
          onClick={() => setReviewOnly((value) => !value)}
        >
          只看需复核 {reviewInScope}
        </button>
      </div>
      <p className="filter-result muted small" aria-live="polite" aria-atomic="true">
        {filteredClaims.length > 0
          ? `显示 ${filteredClaims.length} / ${report.claims.length} 条主张`
          : '没有符合筛选条件的主张。'}
      </p>

      <div className="claim-list">
        {filteredClaims.map((claim) => (
          <article className="claim-card card" key={claim.claim_id}>
            <header className="claim-head">
              <div className="claim-head-left">
                <span className="claim-number mono">{claim.claim_id}</span>
                <span className="claim-lines">
                  {formatLineRange(claim.line_start, claim.line_end)}
                </span>
              </div>
              <VerdictBadge verdict={claim.verdict} />
            </header>

            <p className="claim-text">{claim.text}</p>

            <div className="claim-cites">
              <span className="muted">引用</span>
              {claim.citations.map((key) => (
                <span className="citation-chip mono" key={key}>
                  @{key}
                </span>
              ))}
              <span className="muted small">{formatSeconds(claim.seconds)}</span>
            </div>

            <div className="check-list">
              {claim.checks.map((check) => (
                <div className="check-row" key={`${claim.claim_id}-${check.citation}`}>
                  <div className="check-main">
                    <div className="check-title">
                      <VerdictBadge verdict={check.verdict} size="small" />
                      <span className="mono check-cite">@{check.citation}</span>
                      <span className="check-paper">{check.paper.title || check.paper.paper_key}</span>
                      {check.review_required ? <span className="tag">需复核</span> : null}
                    </div>
                    <p className="reason">{cleanReason(check.reason)}</p>
                    <div className="check-metrics">
                      <span>置信度 {confidenceLabel(check.confidence)}</span>
                      <span>数字 {numberStatusLabel(check.number_status)}</span>
                      {check.evidence ? (
                        <span>
                          证据 p{check.evidence.page} · {check.evidence.unit_id}
                        </span>
                      ) : (
                        <span>无可用证据</span>
                      )}
                      <span>{formatSeconds(check.seconds)}</span>
                    </div>
                    {check.evidence ? (
                      <blockquote className="check-quote">{check.evidence.text}</blockquote>
                    ) : null}
                    {check.evidence ? (
                      <div className="check-quote-metrics">
                        综合 {check.evidence.score.toFixed(3)} · 余弦{' '}
                        {check.evidence.cosine.toFixed(3)} · 覆盖{' '}
                        {formatPercent(check.evidence.keyword_coverage)}
                      </div>
                    ) : null}
                    {check.error ? <p className="error-line">错误：{check.error}</p> : null}
                  </div>
                  <div className="check-actions">
                    <button
                      type="button"
                      className="button ghost small-button"
                      onClick={() => setActive({ claim, check })}
                    >
                      审计详情
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </article>
        ))}
      </div>

      {active ? (
        <EvidenceDrawer
          claim={active.claim}
          check={active.check}
          downloads={report.downloads}
          onClose={() => setActive(null)}
        />
      ) : null}
    </div>
  )
}
