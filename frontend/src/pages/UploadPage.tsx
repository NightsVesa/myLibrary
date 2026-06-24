import { ChangeEvent, DragEvent, useEffect, useState } from 'react'
import { Button, Card, Dialog, Divider, Loading } from 'zelda-hyrule-ui'
import {
  listInbox,
  navigatePanel,
  previewInboxItem,
  uploadFile,
  uploadPreview,
} from '../api'
import type { FilePayload, InboxPreviewPayload } from '../types'
import { PanelShell } from '../components/PanelShell'

type UploadPageProps = {
  token: string
}

export function UploadPage({ token }: UploadPageProps) {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState('')
  const [inbox, setInbox] = useState<FilePayload[]>([])
  const [selected, setSelected] = useState<InboxPreviewPayload | null>(null)
  const [status, setStatus] = useState('选择 DOCX / PDF / Markdown / 图片文件')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function refreshInbox() {
    const payload = await listInbox(token)
    setInbox(payload.items)
  }

  async function choose(nextFile: File | null) {
    setFile(nextFile)
    setSelected(null)
    setError('')
    if (!nextFile) {
      setPreview('')
      return
    }
    setBusy(true)
    setStatus(`正在预览 ${nextFile.name}`)
    try {
      const payload = await uploadPreview(token, nextFile)
      setPreview(payload.preview)
      setStatus('预览已生成')
    } catch (exc) {
      setPreview('')
      setError(exc instanceof Error ? exc.message : '预览失败')
    } finally {
      setBusy(false)
    }
  }

  async function saveAndIngest() {
    if (!file) {
      setError('请先选择文件')
      return
    }
    setBusy(true)
    setError('')
    try {
      const saved = await uploadFile(token, file)
      setStatus(`已保存 ${saved.name}，准备收录`)
      await refreshInbox()
      navigatePanel('ingest', token, { paths: JSON.stringify([saved.path]) })
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  async function selectInbox(item: FilePayload) {
    setError('')
    try {
      const payload = await previewInboxItem(token, item.path)
      setSelected(payload)
      setPreview(payload.content)
      setStatus(`已选择 ${item.name}`)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '暂存预览失败')
    }
  }

  function ingestPaths(paths: string[]) {
    if (!paths.length) return
    navigatePanel('ingest', token, { paths: JSON.stringify(paths) })
  }

  function onInput(event: ChangeEvent<HTMLInputElement>) {
    void choose(event.target.files?.[0] ?? null)
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    void choose(event.dataTransfer.files?.[0] ?? null)
  }

  useEffect(() => {
    void refreshInbox().catch((exc) => setError(exc instanceof Error ? exc.message : '暂存箱加载失败'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <PanelShell
      active="upload"
      eyebrow="SHEIKAH UPLOAD"
      title="文件上传"
      subtitle={status}
      token={token}
    >
      {error && (
        <Dialog type="sheikah" speaker="Panel" showContinue={false}>
          {error}
        </Dialog>
      )}
      <section className="content-grid upload-grid">
        <Card variant="sheikah" title="Upload">
          <div className="drop-zone" onDrop={onDrop} onDragOver={(event) => event.preventDefault()}>
            <input type="file" onChange={onInput} />
            <p>{file?.name ?? '拖入文件，或点击选择'}</p>
          </div>
          <div className="action-row">
            <Button variant="sheikah" loading={busy} onClick={() => void saveAndIngest()}>
              转换并收录
            </Button>
          </div>
          <Divider variant="sheikah" />
          {busy && <Loading tip="Processing..." />}
          <pre className="markdown-preview">{preview || '选择文件后会显示预览'}</pre>
        </Card>

        <Card variant="sheikah" title={`Inbox (${inbox.length})`}>
          <div className="action-row top">
            <Button
              variant="ghost"
              size="small"
              onClick={() => ingestPaths(inbox.map((item) => item.path))}
            >
              全部收录
            </Button>
          </div>
          <div className="result-list">
            {inbox.length === 0 && <p className="empty">暂存箱为空</p>}
            {inbox.map((item) => (
              <div
                key={item.path}
                role="button"
                tabIndex={0}
                className={`inbox-item result-item${selected?.path === item.path ? ' selected' : ''}`}
                onClick={() => void selectInbox(item)}
              >
                <div className="inbox-file-info">
                  <span className="result-name">{item.name}</span>
                  <span className="result-snippet">{item.path}</span>
                </div>
                <Button
                  variant="sheikah"
                  size="small"
                  onClick={(event) => {
                    event.stopPropagation()
                    ingestPaths([item.path])
                  }}
                >
                  收录
                </Button>
              </div>
            ))}
          </div>
        </Card>
      </section>
    </PanelShell>
  )
}
