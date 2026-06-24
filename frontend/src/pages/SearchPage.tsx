import { FormEvent, useEffect, useState } from 'react'
import { Button, Card, Divider, Loading } from 'zelda-hyrule-ui'
import {
  hashParams,
  listLibraryFiles,
  navigatePanel,
  openReader,
  previewLibraryFile,
  previewNote,
  saveFavorite,
  saveTags,
  searchNotes,
} from '../api'
import type {
  LibraryGroup,
  LibraryPreviewPayload,
  LibraryScope,
  PreviewPayload,
  SearchMode,
} from '../types'
import { PanelShell } from '../components/PanelShell'
import { buildCollapsibleGroups, buildTagGroups } from './searchGrouping'
import { MarkdownBlocks } from './MarkdownInline'

type ViewMode = SearchMode | 'sources' | 'wiki'
type ResultItem = {
  path: string
  name: string
  snippet: string
  favorite?: boolean
  tags?: string[]
  scope?: LibraryScope
  kind?: string
  relative_path?: string
}
type PreviewState = PreviewPayload | LibraryPreviewPayload

const MODES: Array<{ mode: ViewMode; label: string }> = [
  { mode: 'fulltext', label: '全文' },
  { mode: 'recent', label: '最近' },
  { mode: 'favorite', label: '收藏' },
  { mode: 'tag', label: '标签' },
  { mode: 'sources', label: '源文件' },
  { mode: 'wiki', label: 'Wiki MD' },
]

function normalizeTags(raw: string) {
  return raw
    .replace(/[，、]/g, ',')
    .split(/[,\s]+/)
    .map((tag) => tag.trim().replace(/^#/, ''))
    .filter(Boolean)
}

function isSearchMode(mode: ViewMode): mode is SearchMode {
  return mode === 'fulltext' || mode === 'recent' || mode === 'favorite' || mode === 'tag'
}

function scopeForMode(mode: ViewMode): LibraryScope {
  return mode === 'wiki' ? 'wiki' : 'notes'
}

function hasNoteMeta(preview: PreviewState): preview is PreviewPayload {
  return !('render_mode' in preview)
}

function shouldUseLibraryPreview(item: ResultItem, activeMode: ViewMode) {
  if (!item.scope) return false
  if (activeMode === 'sources' || activeMode === 'wiki') return true
  if (item.scope === 'wiki') return true
  return item.kind !== 'markdown' && item.kind !== 'md'
}

function canOpenReader(preview: PreviewState) {
  return hasNoteMeta(preview) && preview.scope === 'notes'
}

function initialMode(): ViewMode {
  const scope = hashParams().get('scope')
  if (scope === 'wiki') return 'wiki'
  if (scope === 'notes') return 'sources'
  return 'recent'
}

function matchesRequestedPath(item: ResultItem, requested: string) {
  const normalized = requested.replace(/\\/g, '/')
  return (
    item.path === requested
    || item.relative_path === normalized
    || item.name === requested
  )
}

function mediaUrl(path: string, token: string) {
  if (!path) return ''
  const separator = path.includes('?') ? '&' : '?'
  return `${path}${separator}token=${encodeURIComponent(token)}`
}

type SearchPageProps = {
  token: string
}

export function SearchPage({ token }: SearchPageProps) {
  const [mode, setMode] = useState<ViewMode>(initialMode)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<ResultItem[]>([])
  const [groups, setGroups] = useState<LibraryGroup[]>([])
  const [selected, setSelected] = useState<ResultItem | null>(null)
  const [preview, setPreview] = useState<PreviewState | null>(null)
  const [tagText, setTagText] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('等待检索')
  const [error, setError] = useState('')
  const [collapsedKinds, setCollapsedKinds] = useState<Set<string>>(new Set())

  async function runSearch(
    nextMode: ViewMode = mode,
    nextQuery = query,
    previewFirst = true,
    requestedPath = '',
  ) {
    if (!token) {
      setError('缺少面板令牌')
      return
    }
    setLoading(true)
    setError('')
    try {
      let items: ResultItem[]
      if (isSearchMode(nextMode)) {
        const payload = await searchNotes(token, nextMode, nextQuery)
        items = payload.results
        setGroups([])
        setMessage(`${payload.results.length} 条记录`)
      } else {
        const payload = await listLibraryFiles(token, scopeForMode(nextMode), nextQuery)
        items = payload.items
        setGroups(payload.groups ?? [])
        setMessage(`${nextMode === 'wiki' ? 'Wiki MD' : '源文件'} · ${payload.items.length} 条记录`)
      }
      setResults(items)
      const first = requestedPath
        ? (items.find((item) => matchesRequestedPath(item, requestedPath)) ?? null)
        : (items[0] ?? null)
      if (first && previewFirst) {
        setSelected(first)
        await loadPreview(first, nextMode)
      } else if (requestedPath && previewFirst && nextMode === 'sources') {
        await loadRequestedNotePreview(requestedPath)
      } else {
        setSelected(null)
        setPreview(null)
        setTagText('')
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '检索失败')
    } finally {
      setLoading(false)
    }
  }

  async function loadRequestedNotePreview(path: string) {
    const fallback = {
      path,
      name: path.split(/[\\/]/).pop() || path,
      snippet: '',
    }
    setSelected(fallback)
    const payload = await previewNote(token, path)
    setPreview(payload)
    setTagText(payload.tags.join(' '))
    setMessage(`已打开 ${payload.name}`)
  }

  async function loadPreview(item: ResultItem, activeMode: ViewMode = mode) {
    setSelected(item)
    setError('')
    try {
      const payload = shouldUseLibraryPreview(item, activeMode)
        ? await previewLibraryFile(token, item.scope ?? scopeForMode(activeMode), item.path)
        : await previewNote(token, item.path)
      setPreview(payload)
      setTagText(payload.tags.join(' '))
    } catch (exc) {
      setPreview(null)
      setError(exc instanceof Error ? exc.message : '预览失败')
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    void runSearch()
  }

  async function toggleFavorite() {
    if (!preview) return
    const next = !preview.favorite
    const payload = await saveFavorite(token, preview.path, next, preview.scope)
    const updated = { ...preview, favorite: payload.favorite }
    setPreview(updated)
    setResults((items) => items.map((item) => (
      item.path === updated.path && item.scope === updated.scope
        ? { ...item, favorite: updated.favorite }
        : item
    )))
  }

  async function persistTags() {
    if (!preview) return
    const payload = await saveTags(token, preview.path, normalizeTags(tagText), preview.scope)
    const updated = { ...preview, tags: payload.tags }
    setPreview(updated)
    setTagText(payload.tags.join(' '))
    setResults((items) => items.map((item) => (
      item.path === updated.path && item.scope === updated.scope
        ? { ...item, tags: updated.tags }
        : item
    )))
    if (mode === 'tag') {
      await runSearch('tag', query, false)
    }
    setMessage('标签已保存')
  }

  async function openInReader() {
    if (!preview || !canOpenReader(preview)) return
    await openReader(token, preview.path, query)
    setMessage('已请求打开阅读器')
  }

  function toggleGroup(kind: string) {
    setCollapsedKinds((current) => {
      const next = new Set(current)
      if (next.has(kind)) {
        next.delete(kind)
      } else {
        next.add(kind)
      }
      return next
    })
  }

  useEffect(() => {
    const params = hashParams()
    const nextMode = initialMode()
    const requestedPath = params.get('path') ?? ''
    if (nextMode === 'recent' && !requestedPath) {
      void runSearch('recent', '', false)
      return
    }
    setMode(nextMode)
    void runSearch(nextMode, '', nextMode !== 'recent' || Boolean(requestedPath), requestedPath)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const placeholder = mode === 'tag'
    ? '输入标签名'
    : mode === 'sources'
      ? '筛选源文件名'
      : mode === 'wiki'
        ? '筛选 wiki 路径或内容'
        : '输入关键词'

  function renderResultButton(item: ResultItem) {
    return (
      <button
        type="button"
        key={item.path}
        className={selected?.path === item.path ? 'result-item selected' : 'result-item'}
        onClick={() => void loadPreview(item)}
      >
        <span className="result-name">
          {item.favorite ? '★ ' : ''}
          {item.name}
        </span>
        <span className="result-snippet">{item.snippet || ' '}</span>
        <span className="tag-row">
          {item.kind && <span>{item.kind}</span>}
          {item.relative_path && <span>{item.relative_path}</span>}
          {(item.tags ?? []).map((tag) => <span key={tag}>#{tag}</span>)}
        </span>
      </button>
    )
  }

  function renderPreviewBody() {
    if (!preview) return null
    if (hasNoteMeta(preview)) {
      return <pre className="markdown-preview">{preview.content}</pre>
    }
    if (preview.render_mode === 'markdown') {
      return (
        <MarkdownBlocks
          currentPath={preview.relative_path}
          onWikiLink={(path) => navigatePanel('search', token, { scope: 'wiki', path })}
          source={preview.content}
        />
      )
    }
    if (preview.render_mode === 'image') {
      return (
        <div className="source-media-stage">
          <img src={mediaUrl(preview.media_url, token)} alt={preview.name} />
        </div>
      )
    }
    if (preview.render_mode === 'pdf') {
      return (
        <iframe
          className="source-file-frame"
          src={mediaUrl(preview.media_url, token)}
          title={preview.name}
        />
      )
    }
    if (preview.render_mode === 'docx_html') {
      return (
        <div
          className="source-docx-preview"
          dangerouslySetInnerHTML={{ __html: preview.html }}
        />
      )
    }
    return <pre className="markdown-preview">{preview.content || '此文件类型暂不支持内嵌预览'}</pre>
  }

  const groupedResults = mode === 'wiki'
    ? buildCollapsibleGroups(groups, collapsedKinds)
    : mode === 'tag'
      ? buildTagGroups(results, collapsedKinds)
      : []
  return (
    <PanelShell
      active="search"
      eyebrow="SHEIKAH SEARCH"
      title="知识检索"
      subtitle={message}
      token={token}
    >
      <form className="search-bar" onSubmit={onSubmit}>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={placeholder}
        />
        <Button variant="sheikah" size="small" htmlType="submit" loading={loading}>
          {mode === 'sources' || mode === 'wiki' ? '筛选' : '搜索'}
        </Button>
      </form>

      <div className="mode-row">
        {MODES.map((item) => (
          <button
            className={item.mode === mode ? 'mode active' : 'mode'}
            key={item.mode}
            onClick={() => {
              setMode(item.mode)
              const nextQuery = item.mode === 'recent' || item.mode === 'favorite' ? '' : query
              void runSearch(item.mode, nextQuery, item.mode !== 'recent' && item.mode !== 'favorite')
            }}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </div>

      {error && <div className="search-error" role="alert">{error}</div>}

      <section className="content-grid">
        <Card variant="sheikah" title="Results" className="result-card">
          {loading && <Loading tip="Scanning..." />}
          {!loading && results.length === 0 && <p className="empty">没有匹配记录</p>}
          <div className="result-list">
            {groupedResults.length > 0
              ? groupedResults.map((group) => (
                <section className="library-group" key={group.kind}>
                  <button
                    type="button"
                    className="library-group-toggle"
                    aria-expanded={!group.collapsed}
                    onClick={() => toggleGroup(group.kind)}
                  >
                    <span className="library-group-mark">{group.collapsed ? '+' : '-'}</span>
                    <span>{group.displayLabel}</span>
                    <span className="library-group-count">{group.count}</span>
                  </button>
                  {!group.collapsed && (
                    <div className="library-group-list">
                      {group.items.map(renderResultButton)}
                    </div>
                  )}
                </section>
              ))
              : results.map(renderResultButton)}
          </div>
        </Card>

        <Card variant="sheikah" title="Preview" className="preview-card">
          <div className="preview-shell">
            {!preview && <p className="empty">选择一条记录查看内容</p>}
            {preview && (
              <>
                <div className="preview-meta-bar">
                  <div className="preview-actions compact">
                    <span className="preview-title">{preview.name}</span>
                    <Button
                      variant="ghost"
                      size="small"
                      onClick={() => void toggleFavorite()}
                      title={preview.favorite ? '取消收藏' : '收藏'}
                    >
                      {preview.favorite ? '★' : '☆'}
                    </Button>
                    {canOpenReader(preview) && (
                      <Button
                        variant="sheikah"
                        size="small"
                        onClick={() => void openInReader()}
                        title="阅读"
                      >
                        读
                      </Button>
                    )}
                    {'relative_path' in preview && (
                      <span className="preview-path">{preview.relative_path}</span>
                    )}
                  </div>
                  <div className="tag-editor compact">
                    <span className="tag-editor-label">标签</span>
                    <input
                      value={tagText}
                      onChange={(event) => setTagText(event.target.value)}
                      placeholder="空格分隔"
                    />
                    <Button variant="primary" size="small" onClick={() => void persistTags()}>
                      保存
                    </Button>
                  </div>
                </div>
                <Divider variant="sheikah" />
                <div className="preview-document">
                  {renderPreviewBody()}
                </div>
              </>
            )}
          </div>
        </Card>
      </section>
    </PanelShell>
  )
}
