export const VERDICT_LABELS: Record<string, string> = {
  supported: '支持',
  partial: '部分支持',
  unsupported: '不支持',
  unknown: '无法判断',
}

export function formatTime(value: string | null | undefined): string {
  if (!value) {
    return '—'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function basename(path: string | null | undefined): string {
  if (!path) {
    return '—'
  }
  const parts = path.split(/[\\/]/)
  return parts[parts.length - 1] || path
}

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function formatNumber(value: number): string {
  return value.toLocaleString('zh-CN')
}

export function formatSeconds(value: number): string {
  return `${value.toFixed(2)}s`
}

export function formatLineRange(start: number, end: number): string {
  return start === end ? `第 ${start} 行` : `第 ${start}–${end} 行`
}

export function cleanReason(reason: string): string {
  return reason.replace(/`/g, '')
}

export function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    preflight: '校验输入',
    ingest: 'PDF 入库',
    claim: '逐条核对',
    report: '生成报告',
    done: '已完成',
    failed: '失败',
  }
  return labels[stage] ?? stage
}

export function confidenceLabel(value: string): string {
  const labels: Record<string, string> = { high: '高', medium: '中', low: '低' }
  return labels[value] ?? value
}

export function numberStatusLabel(value: string): string {
  const labels: Record<string, string> = {
    match: '数字一致',
    missing: '数字缺失',
    mismatch: '数字不一致',
    none: '无数字',
  }
  return labels[value] ?? value
}
