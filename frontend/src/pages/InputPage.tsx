import { ClipboardEvent, DragEvent, KeyboardEvent, useRef, useState } from 'react'
import { Button, Card, Dialog, Divider } from 'zelda-hyrule-ui'
import { createNote, navigatePanel, uploadAsset } from '../api'
import { PanelShell } from '../components/PanelShell'

type InputPageProps = {
  token: string
}

export function InputPage({ token }: InputPageProps) {
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [status, setStatus] = useState('Ctrl+Enter 收录  |  Ctrl+Shift+Enter 暂存')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  function insertMarkdown(markdown: string) {
    const textarea = textareaRef.current
    if (!textarea) {
      setContent((value) => `${value}\n${markdown}`)
      return
    }
    const start = textarea.selectionStart
    const end = textarea.selectionEnd
    const next = `${content.slice(0, start)}${markdown}${content.slice(end)}`
    setContent(next)
    window.requestAnimationFrame(() => {
      textarea.focus()
      const pos = start + markdown.length
      textarea.setSelectionRange(pos, pos)
    })
  }

  async function handleImage(file: File) {
    setError('')
    setStatus('正在保存图片资产')
    const asset = await uploadAsset(token, file)
    insertMarkdown(`\n${asset.markdown}\n`)
    setStatus(asset.ocr_status === 'ok' ? '图片已插入，OCR 已完成' : '图片已插入')
  }

  async function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const image = Array.from(event.clipboardData.files).find((file) => file.type.startsWith('image/'))
    if (!image) return
    event.preventDefault()
    try {
      await handleImage(image)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '图片保存失败')
    }
  }

  async function onDrop(event: DragEvent<HTMLTextAreaElement>) {
    event.preventDefault()
    const image = Array.from(event.dataTransfer.files).find((file) => file.type.startsWith('image/'))
    if (!image) return
    try {
      await handleImage(image)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '图片保存失败')
    }
  }

  async function save(ingest: boolean) {
    if (!content.trim()) {
      setError('先写一点内容，再保存')
      return
    }
    setSaving(true)
    setError('')
    try {
      const note = await createNote(token, title, content)
      setTitle('')
      setContent('')
      setStatus(ingest ? `已保存 ${note.name}，准备收录` : `已暂存 ${note.name}`)
      if (ingest) {
        navigatePanel('ingest', token, { paths: JSON.stringify([note.path]) })
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.ctrlKey && event.key === 'Enter') {
      event.preventDefault()
      void save(!event.shiftKey)
    }
  }

  return (
    <PanelShell
      active="input"
      eyebrow="SHEIKAH INPUT"
      title="快速输入"
      subtitle={status}
      token={token}
    >
      {error && (
        <Dialog type="sheikah" speaker="Panel" showContinue={false}>
          {error}
        </Dialog>
      )}

      <section className="single-grid">
        <Card variant="sheikah" title="Title">
          <input
            className="text-input"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="给笔记起个名字..."
          />
          <Divider variant="sheikah" />
          <textarea
            ref={textareaRef}
            className="large-editor"
            value={content}
            onChange={(event) => setContent(event.target.value)}
            onPaste={(event) => void onPaste(event)}
            onDrop={(event) => void onDrop(event)}
            onDragOver={(event) => event.preventDefault()}
            onKeyDown={onKeyDown}
            placeholder="粘贴、拖入图片，或直接键入内容..."
          />
          <div className="action-row">
            <Button variant="ghost" loading={saving} onClick={() => void save(false)}>
              暂存
            </Button>
            <Button variant="sheikah" loading={saving} onClick={() => void save(true)}>
              保存并收录
            </Button>
          </div>
        </Card>
      </section>
    </PanelShell>
  )
}
