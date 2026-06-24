import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Card, Dialog, Divider, Loading } from 'zelda-hyrule-ui'
import {
  createIngestSession,
  hashParams,
  ingestWebSocketUrl,
  previewLibraryFile,
  previewNote,
} from '../api'
import { PanelShell } from '../components/PanelShell'
import type {
  IngestAction,
  IngestCandidate,
  IngestEvent,
  LibraryPreviewPayload,
  PreviewPayload,
} from '../types'

type IngestPageProps = {
  token: string
}

type Stage =
  | 'idle'
  | 'discussion'
  | 'candidates'
  | 'plan'
  | 'executing'
  | 'done'
  | 'error'
  | 'working'
  | 'chat'
  | 'input'
  | 'select'

type IngestLogRole = 'assistant' | 'user' | 'system'

type IngestLogEntry = {
  id: number
  role: IngestLogRole
  text: string
}

type SourcePreview = PreviewPayload | LibraryPreviewPayload

const ACTION_LABELS: Record<string, string> = {
  create: '新增',
  update: '更新',
  light_link: '轻关联',
  skip: '跳过',
  source_check: '需核查',
}

const PLAN_ACTIONS = ['create', 'update', 'light_link', 'skip', 'source_check']

function sourceName(path: string) {
  return path.split(/[\\/]/).pop() || path
}

function isTextSource(path: string) {
  return /\.(md|txt)$/i.test(path)
}

function isLibraryPreview(preview: SourcePreview): preview is LibraryPreviewPayload {
  return 'render_mode' in preview
}

function mediaUrl(path: string, token: string) {
  if (!path) return ''
  const separator = path.includes('?') ? '&' : '?'
  return `${path}${separator}token=${encodeURIComponent(token)}`
}

export function IngestPage({ token }: IngestPageProps) {
  const paths = useMemo(() => {
    const raw = hashParams().get('paths')
    if (!raw) return []
    try {
      const parsed = JSON.parse(raw)
      return Array.isArray(parsed) ? parsed.map(String) : []
    } catch {
      return []
    }
  }, [])
  const [stage, setStage] = useState<Stage>('idle')
  const [status, setStatus] = useState('等待收录任务')
  const [logEntries, setLogEntries] = useState<IngestLogEntry[]>([])
  const [inputText, setInputText] = useState('')
  const [inputMode, setInputMode] = useState<string>('')
  const [candidates, setCandidates] = useState<IngestCandidate[]>([])
  const [actions, setActions] = useState<IngestAction[]>([])
  const [error, setError] = useState('')
  const [sourcePath, setSourcePath] = useState(paths[0] ?? '')
  const [sourcePreview, setSourcePreview] = useState<SourcePreview | null>(null)
  const [sourceError, setSourceError] = useState('')
  const socketRef = useRef<WebSocket | null>(null)
  const logBufferRef = useRef('')
  const flushTimerRef = useRef<number | null>(null)
  const nextLogIdRef = useRef(1)
  const logScrollRef = useRef<HTMLDivElement | null>(null)

  function flushLog() {
    const text = logBufferRef.current
    if (!text) {
      flushTimerRef.current = null
      return
    }
    logBufferRef.current = ''
    flushTimerRef.current = null
    const id = nextLogIdRef.current++
    setLogEntries((items) => {
      const last = items[items.length - 1]
      if (last?.role === 'assistant') {
        return items.map((item, index) => (
          index === items.length - 1 ? { ...item, text: item.text + text } : item
        ))
      }
      return [...items, { id, role: 'assistant', text }]
    })
  }

  function append(text: string) {
    logBufferRef.current += text
    if (flushTimerRef.current === null) {
      flushTimerRef.current = window.setTimeout(flushLog, 50)
    }
  }

  function appendEntry(role: IngestLogRole, text: string) {
    flushLog()
    const id = nextLogIdRef.current++
    setLogEntries((items) => [...items, { id, role, text }])
  }

  function stageFromServer(value: string): Stage {
    if (value.includes('candidate')) return 'candidates'
    if (value.includes('plan')) return 'plan'
    if (value === 'executing') return 'executing'
    if (value === 'discussion') return 'discussion'
    return 'working'
  }

  async function loadSourcePreview(path: string) {
    if (!path) return
    setSourcePath(path)
    setSourceError('')
    try {
      const payload = isTextSource(path)
        ? await previewNote(token, path)
        : await previewLibraryFile(token, 'notes', path)
      setSourcePreview(payload)
    } catch (exc) {
      setSourcePreview(null)
      setSourceError(exc instanceof Error ? exc.message : '源文件预览失败')
    }
  }

  useEffect(() => {
    if (!paths.length) {
      setStatus('没有待收录文件')
      return
    }
    void loadSourcePreview(paths[0])
    let closed = false

    async function start() {
      setStage('working')
      setStatus('正在创建收录会话')
      try {
        const session = await createIngestSession(token, paths)
        if (closed) return
        const socket = new WebSocket(ingestWebSocketUrl(session.session_id, token))
        socketRef.current = socket
        socket.onmessage = (message) => {
          const event = JSON.parse(message.data) as IngestEvent
          if (event.type === 'note') {
            setStatus(`文件 ${event.index}/${event.total}: ${event.name}`)
            appendEntry('system', `文件 ${event.index}/${event.total}: ${event.name}`)
            void loadSourcePreview(event.path)
          } else if (event.type === 'stage') {
            setStage(stageFromServer(event.stage))
            setStatus(event.status)
          } else if (event.type === 'candidates') {
            setCandidates(event.candidates)
            setStage('candidates')
            setStatus('请审阅候选页面')
          } else if (event.type === 'plan') {
            setActions(event.actions)
            setStage('plan')
            setStatus('请确认写入计划')
          } else if (event.type === 'chunk') {
            append(event.text)
          } else if (event.type === 'input_request') {
            flushLog()
            setInputMode(event.mode || 'discussion')
            setStage(event.mode === 'discussion' ? 'chat' : 'input')
          } else if (event.type === 'select') {
            flushLog()
            setStage('select')
            setInputMode('candidates')
          } else if (event.type === 'ready') {
            flushLog()
            setStage('plan')
            setInputMode('plan')
          } else if (event.type === 'done') {
            flushLog()
            setStage('done')
            setInputMode('')
            setStatus('当前文件已完成')
          } else if (event.type === 'session_done') {
            flushLog()
            setStage('done')
            setInputMode('')
            setStatus(`收录完成: 成功 ${event.ok}，失败 ${event.error}`)
          } else if (event.type === 'error') {
            flushLog()
            setStage('error')
            setError(event.message)
          }
        }
        socket.onerror = () => {
          setStage('error')
          setError('收录连接失败')
        }
      } catch (exc) {
        setStage('error')
        setError(exc instanceof Error ? exc.message : '收录会话创建失败')
      }
    }

    void start()
    return () => {
      closed = true
      socketRef.current?.close()
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current)
        flushTimerRef.current = null
      }
      logBufferRef.current = ''
    }
  }, [paths, token])

  useEffect(() => {
    const node = logScrollRef.current
    if (node) {
      node.scrollTop = node.scrollHeight
    }
  }, [logEntries])

  function send(payload: unknown) {
    socketRef.current?.send(JSON.stringify(payload))
  }

  function sendCommand(command: string) {
    send({ type: 'command', command })
  }

  function sendInput(rawText = inputText) {
    const message = rawText.trim()
    if (!message) return
    send({ type: 'input', text: message })
    appendEntry('user', message)
    setInputText('')
    setStage('working')
    setStatus(inputMode === 'discussion' ? '正在继续探究' : '正在修改结构')
  }

  function updateCandidate(path: string, patch: Partial<Pick<IngestCandidate, 'selected' | 'deep'>>) {
    setCandidates((items) => (
      items.map((item) => (item.path === path ? { ...item, ...patch } : item))
    ))
    send({ type: 'candidate_update', path, ...patch })
  }

  function updatePlanAction(path: string, action: string) {
    setActions((items) => (
      items.map((item) => (item.path === path ? { ...item, action } : item))
    ))
    send({ type: 'plan_update', path, action })
  }

  function cancel() {
    send({ type: 'cancel' })
    setStage('done')
    setInputMode('')
    setStatus('已取消')
  }

  const canType = stage === 'chat' || stage === 'input' || stage === 'select'
  const isBusy = stage === 'working' || stage === 'executing'

  function renderSourcePreviewBody() {
    if (sourceError) return <p className="search-error">{sourceError}</p>
    if (!sourcePreview) return <p className="empty">选择源文件后会显示内容</p>
    if (!isLibraryPreview(sourcePreview)) {
      return <pre className="markdown-preview">{sourcePreview.content}</pre>
    }
    if (sourcePreview.render_mode === 'image') {
      return (
        <div className="source-media-stage">
          <img src={mediaUrl(sourcePreview.media_url, token)} alt={sourcePreview.name} />
        </div>
      )
    }
    if (sourcePreview.render_mode === 'pdf') {
      return (
        <iframe
          className="source-file-frame"
          src={mediaUrl(sourcePreview.media_url, token)}
          title={sourcePreview.name}
        />
      )
    }
    if (sourcePreview.render_mode === 'docx_html') {
      return (
        <div
          className="source-docx-preview"
          dangerouslySetInnerHTML={{ __html: sourcePreview.html }}
        />
      )
    }
    return <pre className="markdown-preview">{sourcePreview.content || '此文件类型暂不支持内嵌预览'}</pre>
  }

  return (
    <PanelShell
      active="ingest"
      eyebrow="SHEIKAH INGEST"
      title="Wiki 收录"
      subtitle={status}
      token={token}
    >
      {error && (
        <Dialog type="sheikah" speaker="Panel" showContinue={false}>
          {error}
        </Dialog>
      )}
      <section className="content-grid ingest-workbench">
        <Card variant="sheikah" title="源文件">
          <div className="source-picker">
            {paths.length === 0 && <p className="empty">没有源文件</p>}
            {paths.map((path) => (
              <button
                className={path === sourcePath ? 'source-chip active' : 'source-chip'}
                key={path}
                onClick={() => void loadSourcePreview(path)}
                type="button"
              >
                {sourceName(path)}
              </button>
            ))}
          </div>
          <Divider variant="sheikah" />
          <div className="source-preview-shell">
            {sourcePath && <p className="preview-path">{sourcePath}</p>}
            <div className="preview-document source-preview-document">
              {renderSourcePreviewBody()}
            </div>
          </div>
        </Card>

        <Card variant="sheikah" title="对话探究">
          {isBusy && <Loading tip="Ingesting..." />}
          <div className="ingest-log" ref={logScrollRef}>
            {logEntries.length === 0 && <p className="empty">等待 LLM 读取资料...</p>}
            {logEntries.map((entry) => (
              <div className={`ingest-message ${entry.role}`} key={entry.id}>
                <span className="message-speaker">
                  {entry.role === 'user' ? '你' : entry.role === 'assistant' ? 'LLM' : '系统'}
                </span>
                <pre>{entry.text}</pre>
              </div>
            ))}
          </div>
          <Divider variant="sheikah" />
          <div className="ingest-controls ingest-compose">
            <input
              className="text-input"
              value={inputText}
              disabled={!canType}
              onChange={(event) => setInputText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') sendInput(inputText)
              }}
              placeholder={canType ? '继续提问、强调重点或要求修改' : '等待当前步骤完成...'}
            />
            <Button variant="sheikah" size="small" disabled={!canType} onClick={() => sendInput(inputText)}>
              发送
            </Button>
            {stage === 'discussion' && (
              <Button variant="sheikah" size="small" onClick={() => sendCommand('generate_candidates')}>
                生成候选
              </Button>
            )}
            {stage !== 'done' && (
              <Button variant="ghost" size="small" onClick={cancel}>
                取消
              </Button>
            )}
          </div>
        </Card>

        <Card variant="sheikah" title="结构审阅">
          {(stage === 'candidates' || stage === 'select') && (
            <>
              <div className="ingest-card-list">
                {candidates.length === 0 && <p className="empty">没有候选页面</p>}
                {candidates.map((candidate) => (
                  <article
                    key={candidate.path}
                    className={`ingest-review-item ${candidate.selected ? 'selected' : ''}`}
                  >
                    <div className="ingest-review-head">
                      <div>
                        <p className="result-name">{candidate.title}</p>
                        <p className="result-snippet">{candidate.path}</p>
                      </div>
                      <span className="ingest-pill">
                        {candidate.kind === 'entity' ? '实体' : '概念'}
                      </span>
                    </div>
                    <p className="ingest-reason">{candidate.reason}</p>
                    <div className="ingest-row">
                      <Button
                        variant={candidate.selected ? 'sheikah' : 'ghost'}
                        size="small"
                        onClick={() => updateCandidate(candidate.path, {
                          selected: !candidate.selected,
                        })}
                      >
                        {candidate.selected ? '已选择' : '选择'}
                      </Button>
                      <Button
                        variant={candidate.deep ? 'sheikah' : 'ghost'}
                        size="small"
                        onClick={() => updateCandidate(candidate.path, {
                          selected: true,
                          deep: !candidate.deep,
                        })}
                      >
                        深读
                      </Button>
                      <span className="ingest-pill">{ACTION_LABELS[candidate.action_hint] || candidate.action_hint}</span>
                    </div>
                  </article>
                ))}
              </div>
              <Divider variant="sheikah" />
              <div className="ingest-controls">
                <Button variant="sheikah" onClick={() => sendCommand('generate_plan')}>
                  生成写入计划
                </Button>
              </div>
            </>
          )}

          {stage === 'plan' && (
            <>
              <div className="ingest-card-list">
                {actions.length === 0 && <p className="empty">没有待写入动作</p>}
                {actions.map((action) => (
                  <article key={action.path} className="ingest-review-item selected">
                    <div className="ingest-review-head">
                      <div>
                        <p className="result-name">{action.title}</p>
                        <p className="result-snippet">{action.path}</p>
                      </div>
                      <span className="ingest-pill">{ACTION_LABELS[action.action] || action.action}</span>
                    </div>
                    <p className="ingest-reason">{action.reason}</p>
                    {action.contribution && <p className="ingest-contribution">{action.contribution}</p>}
                    <div className="ingest-row">
                      {PLAN_ACTIONS.map((value) => (
                        <Button
                          key={value}
                          variant={action.action === value ? 'sheikah' : 'ghost'}
                          size="small"
                          onClick={() => updatePlanAction(action.path, value)}
                        >
                          {ACTION_LABELS[value]}
                        </Button>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
              <Divider variant="sheikah" />
              <div className="ingest-controls">
                <Button variant="ghost" onClick={() => sendCommand('back_to_candidates')}>
                  返回候选
                </Button>
                <Button variant="sheikah" onClick={() => sendCommand('execute')}>
                  执行写入
                </Button>
              </div>
            </>
          )}

          {stage !== 'candidates' && stage !== 'select' && stage !== 'plan' && (
            <p className="empty">候选页和写入计划会在这里出现</p>
          )}
        </Card>
      </section>
    </PanelShell>
  )
}
