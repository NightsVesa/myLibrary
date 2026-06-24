export type ApiError = {
  code: string
  message: string
}

export type ApiEnvelope<T> = {
  ok: boolean
  data: T | null
  error: ApiError | null
}

export type SearchMode = 'fulltext' | 'recent' | 'favorite' | 'tag'
export type LibraryScope = 'notes' | 'wiki'

export type SearchResult = {
  path: string
  name: string
  snippet: string
  favorite: boolean
  tags: string[]
}

export type SearchPayload = {
  mode: SearchMode
  query: string
  results: SearchResult[]
}

export type PreviewPayload = {
  scope: 'notes'
  path: string
  relative_path: string
  name: string
  kind: 'markdown'
  content: string
  favorite: boolean
  tags: string[]
}

export type LibraryFile = {
  scope: LibraryScope
  path: string
  relative_path: string
  name: string
  kind: string
  snippet: string
  favorite: boolean
  tags: string[]
}

export type LibraryGroup = {
  kind: string
  label: string
  items: LibraryFile[]
}

export type LibraryFilesPayload = {
  scope: LibraryScope
  query: string
  items: LibraryFile[]
  groups?: LibraryGroup[]
}

export type LibraryPreviewPayload = LibraryFile & {
  render_mode: 'markdown' | 'pdf' | 'image' | 'docx_html' | 'download'
  content_type: string
  media_url: string
  html: string
  content: string
}

export type FilePayload = {
  path: string
  name: string
}

export type PanelRoutePayload = {
  route: string | null
  params: Record<string, string>
}

export type AssetPayload = FilePayload & {
  markdown: string
  ocr_status: 'ok' | 'empty' | 'unavailable' | 'error'
}

export type UploadPreviewPayload = {
  name: string
  preview: string
}

export type InboxPayload = {
  items: FilePayload[]
}

export type InboxPreviewPayload = FilePayload & {
  content: string
}

export type QueryMeta = {
  question: string
  answer_type: string
  used_pages: string[]
  raw_sources: string[]
  suggested_save_title: string
}

export type QueryEvent =
  | { type: 'meta'; meta: QueryMeta }
  | { type: 'thinking'; text: string }
  | { type: 'chunk'; text: string }
  | { type: 'done' }
  | { type: 'error'; message: string }

export type GraphNode = {
  id: string
  title: string
  kind: 'source' | 'entity' | 'concept' | string
  path: string
  summary: string
  mtime: number
  exists: boolean
  degree: number
}

export type GraphEdge = {
  source: string
  target: string
  kind: string
  bidirectional: boolean
}

export type GraphPayload = {
  nodes: GraphNode[]
  edges: GraphEdge[]
  diagnostics: {
    orphan: string[]
    missing: string[]
    hub: string[]
  }
}

export type LintFinding = {
  severity: 'error' | 'warn' | 'info'
  kind: string
  location: string
  message: string
  suggestion: string
  priority: 'P0' | 'P1' | 'P2'
  fixable: boolean
  source: 'static' | 'llm'
}

export type LintFixFile = {
  path: string
  original: string
  updated: string
  issues: string[]
}

export type LintFixPreview = {
  files: LintFixFile[]
  summary: string
}

export type LintEvent =
  | { type: 'progress'; count: number }
  | { type: 'finding'; finding: LintFinding }
  | { type: 'done'; report: string; count: number }
  | { type: 'error'; message: string }

export type IngestCandidate = {
  kind: 'entity' | 'concept' | string
  path: string
  title: string
  reason: string
  confidence: number
  default_selected: boolean
  action_hint: string
  selected: boolean
  deep: boolean
}

export type IngestAction = {
  action: 'create' | 'update' | 'light_link' | 'skip' | 'source_check' | string
  path: string
  title: string
  reason: string
  contribution: string
}

export type IngestEvent =
  | { type: 'note'; path: string; name: string; index: number; total: number }
  | { type: 'stage'; stage: string; status: string }
  | { type: 'candidates'; candidates: IngestCandidate[] }
  | { type: 'plan'; actions: IngestAction[] }
  | { type: 'chunk'; text: string }
  | { type: 'input_request'; mode?: string; actions?: string[] }
  | { type: 'select' }
  | { type: 'ready' }
  | { type: 'done' }
  | { type: 'session_done'; ok: number; error: number }
  | { type: 'error'; message: string }
