import { FormEvent, useEffect, useRef, useState } from 'react'
import { Button, Card, Dialog, Divider } from 'zelda-hyrule-ui'
import { navigatePanel, queryWiki, saveQueryAnswer } from '../api'
import { PanelShell } from '../components/PanelShell'
import { MarkdownInline } from './MarkdownInline'
import type { QueryEvent, QueryMeta } from '../types'

type ChatPageProps = {
  token: string
}

type Turn = {
  question: string
  answer: string
  thinking: string
  meta: QueryMeta | null
}

let cachedTurns: Turn[] = []
let cachedStatus = '向知识库提问'

function isNearConversationBottom(node: HTMLDivElement): boolean {
  return node.scrollHeight - node.scrollTop - node.clientHeight < 48
}

export function ChatPage({ token }: ChatPageProps) {
  const [question, setQuestion] = useState('')
  const [turns, setTurnsState] = useState<Turn[]>(cachedTurns)
  const [streaming, setStreaming] = useState(false)
  const [status, setStatusState] = useState(cachedStatus)
  const [error, setError] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const conversationRef = useRef<HTMLDivElement | null>(null)
  const shouldFollowRef = useRef(true)

  function setTurns(update: Turn[] | ((items: Turn[]) => Turn[])) {
    setTurnsState((items) => {
      const next = typeof update === 'function' ? update(items) : update
      cachedTurns = next
      return next
    })
  }

  function setStatus(text: string) {
    cachedStatus = text
    setStatusState(text)
  }

  function updateLast(updater: (turn: Turn) => Turn) {
    setTurns((items) => items.map((item, index) => (
      index === items.length - 1 ? updater(item) : item
    )))
  }

  useEffect(() => {
    setTurns(cachedTurns)
  }, [])

  useEffect(() => {
    const node = conversationRef.current
    if (node && shouldFollowRef.current) {
      node.scrollTop = node.scrollHeight
    }
  }, [turns])

  function handleConversationScroll() {
    const node = conversationRef.current
    if (node) {
      shouldFollowRef.current = isNearConversationBottom(node)
    }
  }

  async function ask(event?: FormEvent) {
    event?.preventDefault()
    const text = question.trim()
    if (!text || streaming) return
    shouldFollowRef.current = true
    setQuestion('')
    setError('')
    setStatus('正在检索 wiki')
    setStreaming(true)
    setTurns((items) => [...items, { question: text, answer: '', thinking: '', meta: null }])
    const controller = new AbortController()
    abortRef.current = controller
    try {
      await queryWiki(token, text, (eventData: QueryEvent) => {
        if (eventData.type === 'meta') {
          updateLast((turn) => ({ ...turn, meta: eventData.meta }))
          setStatus(`${eventData.meta.used_pages.length} 个 wiki 页面进入上下文`)
        } else if (eventData.type === 'thinking') {
          updateLast((turn) => ({ ...turn, thinking: turn.thinking + eventData.text }))
        } else if (eventData.type === 'chunk') {
          updateLast((turn) => ({ ...turn, answer: turn.answer + eventData.text }))
        } else if (eventData.type === 'error') {
          setError(eventData.message)
        } else if (eventData.type === 'done') {
          setStatus('回答完成')
        }
      }, controller.signal)
    } catch (exc) {
      if (!controller.signal.aborted) {
        setError(exc instanceof Error ? exc.message : '问答失败')
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }

  function stop() {
    abortRef.current?.abort()
    setStreaming(false)
    setStatus('已停止生成')
  }

  function clearChat() {
    abortRef.current?.abort()
    setStreaming(false)
    setError('')
    setTurns([])
    setStatus('向知识库提问')
  }

  async function saveLast() {
    const last = turns[turns.length - 1]
    if (!last || !last.answer.trim()) return
    try {
      const saved = await saveQueryAnswer(token, {
        question: last.question,
        answer: last.answer,
        used_pages: last.meta?.used_pages ?? [],
        raw_sources: last.meta?.raw_sources ?? [],
        answer_type: last.meta?.answer_type ?? 'direct_answer',
      })
      setStatus(`已保存 ${saved.name}`)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '保存失败')
    }
  }

  return (
    <PanelShell
      active="chat"
      eyebrow="SHEIKAH CHAT"
      title="知识问答"
      subtitle={status}
      token={token}
    >
      {error && (
        <Dialog type="sheikah" speaker="Panel" showContinue={false}>
          {error}
        </Dialog>
      )}
      <section className="single-grid chat-layout">
        <Card variant="sheikah" title="Conversation">
          <div className="conversation" onScroll={handleConversationScroll} ref={conversationRef}>
            {turns.length === 0 && <p className="empty">输入问题后，将基于 wiki 流式回答</p>}
            {turns.map((turn, index) => (
              <article className="turn chat-turn" key={`${turn.question}-${index}`}>
                <div className="chat-message user">
                  <p className="speaker">你</p>
                  <p>{turn.question}</p>
                </div>
                {turn.thinking && (
                  <div className="chat-message assistant thinking-message">
                    <p className="speaker assistant">思考</p>
                    <pre className="thinking">{turn.thinking}</pre>
                  </div>
                )}
                <div className="chat-message assistant">
                  <p className="speaker assistant">LLM</p>
                  <div className="answer">
                    <MarkdownInline
                      onWikiLink={(path) => navigatePanel('search', token, { scope: 'wiki', path })}
                      text={turn.answer || '...'}
                    />
                  </div>
                </div>
                {turn.meta && (
                  <div className="source-row">
                    {turn.meta.used_pages.map((page) => (
                      <button
                        key={page}
                        onClick={() => navigatePanel('search', token, { scope: 'wiki', path: page })}
                        type="button"
                      >
                        {page}
                      </button>
                    ))}
                    {turn.meta.raw_sources.map((source) => (
                      <button
                        key={source}
                        onClick={() => navigatePanel('search', token, { scope: 'notes', path: source })}
                        type="button"
                      >
                        {source}
                      </button>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </div>
          <Divider variant="sheikah" />
          <form className="chat-input" onSubmit={(event) => void ask(event)}>
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="输入你的问题..."
              disabled={streaming}
            />
            <Button variant={streaming ? 'danger' : 'sheikah'} onClick={streaming ? stop : undefined} htmlType={streaming ? 'button' : 'submit'}>
              {streaming ? '停止' : '发送'}
            </Button>
            <Button variant="ghost" htmlType="button" onClick={() => void saveLast()}>
              保存
            </Button>
            <Button variant="ghost" htmlType="button" onClick={clearChat}>
              清空
            </Button>
          </form>
        </Card>
      </section>
    </PanelShell>
  )
}
