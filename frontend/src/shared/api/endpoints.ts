import type {
  AppConfig,
  BibliographyFile,
  DraftFile,
  Health,
  Job,
  MemoryHandoffPayload,
  MemoryKind,
  MemoryPayload,
  MemoryProjectsPayload,
  MemorySearchPayload,
  MemoryWritePayload,
  PaperRecord,
  ReportListItem,
  ReportPayload,
  UploadResponse,
} from '../types'
import { request } from './client'

export function getConfig(): Promise<AppConfig> {
  return request<AppConfig>('/api/config')
}

export function getHealth(): Promise<Health> {
  return request<Health>('/api/health')
}

export function getPapers(): Promise<{ papers: PaperRecord[]; count: number }> {
  return request('/api/papers')
}

export function getDrafts(): Promise<{ drafts: DraftFile[] }> {
  return request('/api/drafts')
}

export function getBibliographies(): Promise<{ bibliographies: BibliographyFile[] }> {
  return request('/api/bibliographies')
}

export function getReports(): Promise<{ reports: ReportListItem[] }> {
  return request('/api/reports')
}

export function getReport(runId: string): Promise<ReportPayload> {
  return request(`/api/reports/${encodeURIComponent(runId)}`)
}

export function getJob(jobId: string): Promise<{ job: Job }> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}`)
}

export function getJobs(): Promise<{ jobs: Job[] }> {
  return request('/api/jobs')
}

export function startAudit(payload: {
  draft: string
  bib: string
  paragraphs: number
  per_leg: number
}): Promise<{ job: Job }> {
  return request('/api/audits', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function uploadPdf(
  file: File,
  meta: { title?: string; authors?: string; year?: number | null },
): Promise<UploadResponse> {
  const params = new URLSearchParams({ filename: file.name })
  if (meta.title?.trim()) params.set('title', meta.title.trim())
  if (meta.authors?.trim()) params.set('authors', meta.authors.trim())
  if (meta.year) params.set('year', String(meta.year))
  return request(`/api/uploads?${params.toString()}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/pdf' },
    body: file,
  })
}

export function getMemoryProjects(): Promise<MemoryProjectsPayload> {
  return request('/api/memory/projects')
}

export function getMemory(
  project: string,
  kind?: MemoryKind | null,
  limit = 20,
  offset = 0,
): Promise<MemoryPayload> {
  const params = new URLSearchParams({
    project,
    limit: String(limit),
    offset: String(offset),
  })
  if (kind) {
    params.set('kind', kind)
  }
  return request(`/api/memory?${params.toString()}`)
}

export function searchMemory(project: string, q: string): Promise<MemorySearchPayload> {
  const params = new URLSearchParams({ project, q })
  return request(`/api/memory/search?${params.toString()}`)
}

export function writeMemory(payload: {
  project: string
  kind: MemoryKind
  text: string
  reason?: string
}): Promise<MemoryWritePayload> {
  return request('/api/memory/entries', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function continueMemoryHandoff(project: string): Promise<MemoryHandoffPayload> {
  return request('/api/memory/handoff/continue', {
    method: 'POST',
    body: JSON.stringify({ project }),
  })
}
