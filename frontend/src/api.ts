import type {
  ApiEnvelope,
  AssetPayload,
  FilePayload,
  GraphPayload,
  InboxPayload,
  InboxPreviewPayload,
  LibraryFilesPayload,
  LibraryPreviewPayload,
  LibraryScope,
  LintEvent,
  LintFinding,
  LintFixPreview,
  PanelRoutePayload,
  PreviewPayload,
  QueryEvent,
  SearchMode,
  SearchPayload,
  UploadPreviewPayload,
} from './types'

export function panelToken(): string {
  const hashQuery = window.location.hash.split('?')[1] ?? ''
  const token = new URLSearchParams(hashQuery || window.location.search).get('token')
  return token ?? ''
}

export function hashParams(): URLSearchParams {
  return new URLSearchParams(window.location.hash.split('?')[1] ?? '')
}

export function currentRoute(): string {
  return window.location.hash.split('?')[0].replace(/^#\/?/, '') || 'search'
}

export function navigatePanel(route: string, token: string, params: Record<string, string> = {}) {
  const query = new URLSearchParams({ token, ...params })
  window.location.hash = `/${route}?${query.toString()}`
}

function buildHeaders(token: string, init?: RequestInit): Headers {
  const headers = new Headers(init?.headers)
  headers.set('X-Panel-Token', token)
  if (!(init?.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  return headers
}

async function request<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: buildHeaders(token, init),
  })
  const raw = await response.text()
  let payload: ApiEnvelope<T>
  try {
    payload = JSON.parse(raw) as ApiEnvelope<T>
  } catch {
    throw new Error(raw ? `Response was not JSON: ${raw}` : `Response was not JSON: HTTP ${response.status}`)
  }
  if (!response.ok || !payload.ok || payload.data === null) {
    throw new Error(payload.error?.message || 'Request failed')
  }
  return payload.data
}

function parseNdjsonLine<T>(line: string): T {
  try {
    return JSON.parse(line) as T
  } catch {
    throw new Error(`Stream response was not JSON: ${line}`)
  }
}

async function streamNdjson<T>(
  path: string,
  token: string,
  body: unknown,
  onEvent: (event: T) => void,
  signal?: AbortSignal,
) {
  const response = await fetch(path, {
    method: 'POST',
    headers: buildHeaders(token, { body: JSON.stringify(body) }),
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) {
    const raw = await response.text()
    if (raw) {
      let payload: ApiEnvelope<unknown>
      try {
        payload = JSON.parse(raw) as ApiEnvelope<unknown>
      } catch {
        throw new Error(`Stream response was not JSON: ${raw}`)
      }
      throw new Error(payload.error?.message || `Request failed: ${response.status}`)
    }
    throw new Error(`Request failed: ${response.status}`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (line.trim()) onEvent(parseNdjsonLine<T>(line))
    }
  }
  if (buffer.trim()) onEvent(parseNdjsonLine<T>(buffer))
}

export function pollPanelRouteCommand(token: string) {
  return request<PanelRoutePayload>('/api/panel-route', token)
}

export function createNote(token: string, title: string, content: string) {
  return request<FilePayload>('/api/notes', token, {
    method: 'POST',
    body: JSON.stringify({ title, content }),
  })
}

export function uploadAsset(token: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<AssetPayload>('/api/assets', token, {
    method: 'POST',
    body: form,
  })
}

export function uploadPreview(token: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<UploadPreviewPayload>('/api/uploads/preview', token, {
    method: 'POST',
    body: form,
  })
}

export function uploadFile(token: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<FilePayload>('/api/uploads', token, {
    method: 'POST',
    body: form,
  })
}

export function listInbox(token: string) {
  return request<InboxPayload>('/api/inbox', token)
}

export function previewInboxItem(token: string, path: string) {
  const params = new URLSearchParams({ path })
  return request<InboxPreviewPayload>(`/api/inbox/preview?${params}`, token)
}

export function deleteInboxItem(token: string, path: string) {
  const params = new URLSearchParams({ path })
  return request<FilePayload>(`/api/inbox?${params}`, token, {
    method: 'DELETE',
  })
}

export function searchNotes(token: string, mode: SearchMode, query: string) {
  const params = new URLSearchParams({ mode })
  if (query.trim()) params.set('q', query.trim())
  return request<SearchPayload>(`/api/search?${params}`, token)
}

export function previewNote(token: string, path: string) {
  const params = new URLSearchParams({ path })
  return request<PreviewPayload>(`/api/notes/preview?${params}`, token)
}

export function listLibraryFiles(token: string, scope: LibraryScope, query = '') {
  const params = new URLSearchParams({ scope })
  if (query.trim()) params.set('q', query.trim())
  return request<LibraryFilesPayload>(`/api/library/files?${params}`, token)
}

export function previewLibraryFile(token: string, scope: LibraryScope, path: string) {
  const params = new URLSearchParams({ scope, path })
  return request<LibraryPreviewPayload>(`/api/library/files/preview?${params}`, token)
}

export function saveFavorite(token: string, path: string, favorite: boolean, scope: LibraryScope = 'notes') {
  return request<{ favorite: boolean }>('/api/meta/favorite', token, {
    method: 'POST',
    body: JSON.stringify({ scope, path, favorite }),
  })
}

export function saveTags(token: string, path: string, tags: string[], scope: LibraryScope = 'notes') {
  return request<{ tags: string[] }>('/api/meta/tags', token, {
    method: 'POST',
    body: JSON.stringify({ scope, path, tags }),
  })
}

export function openReader(token: string, path: string, query: string) {
  return request<{ opened: boolean }>('/api/notes/open-reader', token, {
    method: 'POST',
    body: JSON.stringify({ path, query }),
  })
}

export function queryWiki(
  token: string,
  question: string,
  onEvent: (event: QueryEvent) => void,
  signal?: AbortSignal,
) {
  return streamNdjson<QueryEvent>('/api/wiki/query', token, { question }, onEvent, signal)
}

export function saveQueryAnswer(
  token: string,
  payload: {
    question: string
    answer: string
    used_pages: string[]
    raw_sources: string[]
    answer_type: string
  },
) {
  return request<FilePayload>('/api/wiki/query/save', token, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function loadGraph(token: string) {
  return request<GraphPayload>('/api/wiki/graph', token)
}

export function runLint(token: string, onEvent: (event: LintEvent) => void) {
  return streamNdjson<LintEvent>('/api/wiki/lint', token, {}, onEvent)
}

export function fixLint(token: string, findings: LintFinding[]) {
  return request<{ fixed: number; findings: LintFinding[] }>('/api/wiki/lint/fix', token, {
    method: 'POST',
    body: JSON.stringify({ findings }),
  })
}

export function previewLintFix(token: string, findings: LintFinding[]) {
  return request<{
    fixed: number
    findings: LintFinding[]
    preview: LintFixPreview | null
    llm_available: boolean
    llm_error: string | null
  }>('/api/wiki/lint/fix-preview', token, {
    method: 'POST',
    body: JSON.stringify({ findings }),
  })
}

export function applyLintFixPreview(token: string, preview: LintFixPreview) {
  return request<{ written: number; findings: LintFinding[] }>('/api/wiki/lint/apply-preview', token, {
    method: 'POST',
    body: JSON.stringify({ preview }),
  })
}

export function rebuildLintIndex(token: string) {
  return request<{ findings: LintFinding[] }>('/api/wiki/lint/rebuild-index', token, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function createIngestSession(token: string, paths: string[]) {
  return request<{ session_id: string; count: number }>('/api/wiki/ingest', token, {
    method: 'POST',
    body: JSON.stringify({ paths }),
  })
}

export function ingestWebSocketUrl(sessionId: string, token: string) {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const query = new URLSearchParams({ token })
  return `${scheme}//${window.location.host}/api/wiki/ingest/${sessionId}?${query}`
}
