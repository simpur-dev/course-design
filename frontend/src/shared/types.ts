export type Verdict = 'supported' | 'partial' | 'unsupported' | 'unknown'

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed'

export interface PaperRecord {
  paper_key: string
  title: string
  authors: string
  year: number | null
  source_url: string
  file_name: string
  file_sha256: string
  page_count: number
  para_count: number
  sent_count: number
  unit_mode: string
  ingested_at: string
}

export interface EvidenceRecord {
  unit_id: string
  paper_key: string
  page: number
  unit_type: string
  parent_id: string
  text: string
  score: number
  cosine: number
  keyword_coverage: number
  number_status: string
}

export interface ParagraphHit {
  unit_id: string
  paper_key: string
  page: number
  unit_type: string
  text: string
  parent_id: string
  rrf_score: number
  fulltext_rank: number | null
  vector_rank: number | null
  fulltext_score: number | null
  vector_distance: number | null
}

export interface CitationCheck {
  citation: string
  paper: PaperRecord
  verdict: Verdict
  confidence: string
  review_required: boolean
  reason: string
  keywords: string[]
  number_status: string
  seconds: number
  error: string | null
  evidence: EvidenceRecord | null
  paragraph_hits: ParagraphHit[]
  sentence_candidates: EvidenceRecord[]
}

export interface ClaimResult {
  claim_id: string
  line_start: number
  line_end: number
  text: string
  citations: string[]
  verdict: Verdict
  seconds: number
  checks: CitationCheck[]
}

export interface ReportSummary {
  claims: number
  citations: number
  claim_verdicts: Record<Verdict, number>
  citation_verdicts: Record<Verdict, number>
  review_required: number
  errors: number
}

export interface ReportPayload {
  run_id: string
  generated_at: string
  draft: string
  bib: string
  verifier: string
  embedding_model: string
  unit_mode: string
  summary: ReportSummary
  warnings: string[]
  claims: ClaimResult[]
  files?: Record<string, string>
  downloads?: Record<string, string>
  memory?: MemorySync
}

export interface ReportListItem {
  run_id: string
  generated_at: string
  draft: string
  bib: string
  verifier: string
  summary: ReportSummary
  warnings: string[]
  downloads: Record<string, string>
}

export interface IngestResult {
  key: string
  status: string
  page_count: number
  para_count: number
  sent_count: number
  embedded: number
  computed: number
  cached: number
  batches: number
  seconds: number
  unit_count: number
  error: string
}

export interface Job {
  id: string
  status: JobStatus
  stage: string
  progress: number
  message: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  claim_id: string | null
  kind: 'audit' | 'ingest'
  paper_key: string | null
  result: ReportPayload | IngestResult | null
  error: string | null
  hint: string | null
}

export interface UploadedPaper {
  key: string
  title: string
  authors: string
  year: number | null
  file: string
}

export interface UploadResponse {
  job: Job
  paper: UploadedPaper
  duplicate: boolean
}

export function isIngestResult(
  result: ReportPayload | IngestResult | null,
): result is IngestResult {
  return Boolean(result && 'unit_count' in result)
}

export function isReportPayload(
  result: ReportPayload | IngestResult | null,
): result is ReportPayload {
  return Boolean(result && 'run_id' in result)
}

export interface AppConfig {
  version: string
  verifier: string
  verifier_model: string | null
  embedding_provider: string
  baseline: boolean
  memory_enabled: boolean
  frontend_built: boolean
  baseline_notice: string
}

export interface CheckRecord {
  name: string
  ok: boolean
  detail: string
  hint: string | null
}

export interface Health {
  ok: boolean
  checks: CheckRecord[]
}

export interface DraftFile {
  path: string
  name: string
  content: string
  line_count: number
  char_count: number
  citation_count: number
  truncated: boolean
  updated_at: string
}

export interface BibliographyFile {
  path: string
  name: string
  updated_at: string
}

export type MemoryKind = 'criterion' | 'decision' | 'constraint' | 'next_step'

export interface MemoryEntryRecord {
  artifact_id: string
  revision: number
  kind: string
  text: string
  state: string
  state_version: number
}

export interface ArtifactReference {
  family: string
  artifact_id: string
  revision: number
}

export interface HandoffCitation {
  kind: string
  artifact_ref: ArtifactReference
}

export interface HandoffStatement {
  text: string
  citations: HandoffCitation[]
}

export interface HandoffContent {
  schema: string
  objective: string
  state: HandoffStatement[]
  disposition: 'continuable' | 'blocked' | 'complete' | string
  next_action: HandoffStatement
  omissions: { text: string; citation: HandoffCitation }[]
}

export interface HandoffEvidenceCheck {
  claim: string
  state_index: number | null
  status: string
  unavailable_evidence: string[]
}

export interface HandoffView {
  status: 'empty' | 'resolved' | string
  trust: string
  content: HandoffContent | null
  evidence_checks: HandoffEvidenceCheck[]
  selected_revision: ArtifactReference | null
  current_revision: ArtifactReference | null
  revision?: number | null
  committed?: boolean
}

export interface MemorySync {
  ok: boolean
  enabled: boolean
  project: string | null
  scope_title: string | null
  scope_id: string | null
  written: number
  skipped: number
  entries: MemoryEntryRecord[]
  handoff: HandoffView | null
  error: string | null
  hint: string | null
  run_id?: string
  written_at?: string
}

export interface MemoryProject {
  project: string
  title: string
  scope_id: string | null
  version?: number
}

export interface MemoryProjectsPayload {
  projects: MemoryProject[]
  default: string
  kinds: MemoryKind[]
}

export interface MemoryScope {
  scope_id: string
  title: string
  summary: string
  version: number
}

export interface MemoryPayload {
  available: boolean
  project: string
  scope: MemoryScope
  entries: MemoryEntryRecord[]
  total: number
  counts: Record<string, number>
  handoff: HandoffView
  kinds: MemoryKind[]
  offset: number
  limit: number
  has_more: boolean
}

export interface MemorySearchHit {
  memory: {
    artifact: ArtifactReference
    kind: string
    text: string
    state: string
    state_version: number
    merged_into_id: string | null
  }
  score: number
  matched_by: string[]
}

export interface MemorySearchPayload {
  available: boolean
  project: string
  query: string
  hits: MemorySearchHit[]
}

export interface MemoryWritePayload {
  available: boolean
  project: string
  changed: boolean
  records: MemoryEntryRecord[]
}

export interface MemoryHandoffPayload {
  available: boolean
  project: string
  handoff: HandoffView
}
