export type RouteState =
  | { name: 'audit'; demo: boolean }
  | { name: 'papers' }
  | { name: 'reports' }
  | { name: 'report'; runId: string }
  | { name: 'memory'; project: string | null }
  | { name: 'system' }
  | { name: 'not-found' }

export function normalizeHash(hash: string): string {
  const raw = hash.replace(/^#/, '')
  return raw.startsWith('/') ? raw : `/${raw}`
}

export function parseRoute(route: string): RouteState {
  if (route === '/audit/demo') {
    return { name: 'audit', demo: true }
  }
  if (route === '/') {
    return { name: 'audit', demo: false }
  }
  if (route === '/papers') {
    return { name: 'papers' }
  }
  if (route === '/reports') {
    return { name: 'reports' }
  }
  const reportMatch = route.match(/^\/reports\/([^/]+)$/)
  if (reportMatch) {
    let runId = reportMatch[1]
    try {
      runId = decodeURIComponent(runId)
    } catch {
      // Keep the raw segment when it is not valid percent-encoding.
    }
    return { name: 'report', runId }
  }
  if (route === '/memory' || route.startsWith('/memory?')) {
    const queryStart = route.indexOf('?')
    const project = queryStart >= 0 ? new URLSearchParams(route.slice(queryStart + 1)).get('project') : null
    return { name: 'memory', project }
  }
  if (route === '/system') {
    return { name: 'system' }
  }
  return { name: 'not-found' }
}
