import { VERDICT_LABELS } from '../../../shared/format'
import type { Verdict } from '../../../shared/types'

export function VerdictBadge({
  verdict,
  size = 'normal',
}: {
  verdict: Verdict
  size?: 'normal' | 'small'
}) {
  return (
    <span className={`verdict verdict-${verdict}${size === 'small' ? ' verdict-small' : ''}`}>
      <span className="verdict-dot" aria-hidden="true" />
      {VERDICT_LABELS[verdict] ?? verdict}
    </span>
  )
}
