import { useMemo, useState } from 'react'
import { Button, Card, Dialog, Loading } from 'zelda-hyrule-ui'
import { applyLintFixPreview, previewLintFix, rebuildLintIndex, runLint } from '../api'
import { PanelShell } from '../components/PanelShell'
import type { LintEvent, LintFinding, LintFixPreview } from '../types'

type LintPageProps = {
  token: string
}

type LintOperation = 'idle' | 'checking' | 'fixing' | 'applying' | 'rebuilding'

const PRIORITIES: Array<LintFinding['priority']> = ['P0', 'P1', 'P2']
const SUGGESTION_KINDS = new Set(['investigation', 'next_source'])

type DiffLine = {
  kind: 'context' | 'add' | 'remove'
  text: string
}

type SideBySideDiffRow = {
  kind: 'context' | 'add' | 'remove' | 'change'
  oldText: string
  newText: string
  oldLine: number | null
  newLine: number | null
}

function findingKey(finding: LintFinding, index: number) {
  return `${finding.priority}:${finding.kind}:${finding.location}:${index}`
}

function buildDiffOps(original: string, updated: string): DiffLine[] {
  const oldLines = original.split(/\r?\n/)
  const newLines = updated.split(/\r?\n/)
  const dp = Array.from({ length: oldLines.length + 1 }, () => Array(newLines.length + 1).fill(0))

  for (let i = oldLines.length - 1; i >= 0; i -= 1) {
    for (let j = newLines.length - 1; j >= 0; j -= 1) {
      dp[i][j] = oldLines[i] === newLines[j]
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  const lines: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < oldLines.length && j < newLines.length) {
    if (oldLines[i] === newLines[j]) {
      lines.push({ kind: 'context', text: oldLines[i] })
      i += 1
      j += 1
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      lines.push({ kind: 'remove', text: oldLines[i] })
      i += 1
    } else {
      lines.push({ kind: 'add', text: newLines[j] })
      j += 1
    }
  }
  while (i < oldLines.length) {
    lines.push({ kind: 'remove', text: oldLines[i] })
    i += 1
  }
  while (j < newLines.length) {
    lines.push({ kind: 'add', text: newLines[j] })
    j += 1
  }
  return lines
}

function buildSideBySideDiff(original: string, updated: string): SideBySideDiffRow[] {
  const ops = buildDiffOps(original, updated)
  const rows: SideBySideDiffRow[] = []
  let oldLine = 1
  let newLine = 1
  let index = 0

  while (index < ops.length) {
    const op = ops[index]
    if (op.kind === 'context') {
      rows.push({
        kind: 'context',
        oldText: op.text,
        newText: op.text,
        oldLine,
        newLine,
      })
      oldLine += 1
      newLine += 1
      index += 1
      continue
    }

    const removes: Array<{ text: string; line: number }> = []
    const adds: Array<{ text: string; line: number }> = []
    while (index < ops.length && ops[index].kind !== 'context') {
      const current = ops[index]
      if (current.kind === 'remove') {
        removes.push({ text: current.text, line: oldLine })
        oldLine += 1
      } else {
        adds.push({ text: current.text, line: newLine })
        newLine += 1
      }
      index += 1
    }

    const count = Math.max(removes.length, adds.length)
    for (let i = 0; i < count; i += 1) {
      const removed = removes[i]
      const added = adds[i]
      rows.push({
        kind: removed && added ? 'change' : removed ? 'remove' : 'add',
        oldText: removed?.text ?? '',
        newText: added?.text ?? '',
        oldLine: removed?.line ?? null,
        newLine: added?.line ?? null,
      })
    }
  }

  return rows
}

function buildPreviewIssuesByFile(preview: LintFixPreview, findings: LintFinding[]) {
  const byFile: Record<string, LintFinding[]> = {}
  for (const file of preview.files) {
    byFile[file.path] = findings.filter((finding) => {
      return finding.location === file.path || (file.path === 'index.md' && finding.location === 'wiki')
    })
  }
  return byFile
}

export function LintPage({ token }: LintPageProps) {
  const [findings, setFindings] = useState<LintFinding[]>([])
  const [selectedFindingKeys, setSelectedFindingKeys] = useState<Set<string>>(new Set())
  const [operation, setOperation] = useState<LintOperation>('idle')
  const [status, setStatus] = useState('Wiki 健康检查')
  const [report, setReport] = useState('')
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<LintFixPreview | null>(null)
  const [previewIssuesByFile, setPreviewIssuesByFile] = useState<Record<string, LintFinding[]>>({})
  const [openPreviewFiles, setOpenPreviewFiles] = useState<Set<string>>(new Set())
  const [acceptedPreviewPaths, setAcceptedPreviewPaths] = useState<Set<string>>(new Set())
  const running = operation !== 'idle'
  const loadingTip = {
    idle: '',
    checking: 'Checking...',
    fixing: 'Fixing...',
    applying: 'Applying...',
    rebuilding: 'Rebuilding...',
  }[operation]

  const keyedFindings = useMemo(() => {
    return findings.map((finding, index) => ({
      finding,
      key: findingKey(finding, index),
      actionable: !SUGGESTION_KINDS.has(finding.kind),
    }))
  }, [findings])
  const actionable = keyedFindings.filter((item) => item.actionable)
  const selectedFindings = actionable.filter((item) => selectedFindingKeys.has(item.key)).map((item) => item.finding)
  const acceptedPreviewFiles = useMemo(() => {
    return preview?.files.filter((file) => acceptedPreviewPaths.has(file.path)) ?? []
  }, [acceptedPreviewPaths, preview])
  const acceptedPreview = useMemo<LintFixPreview | null>(() => {
    if (!preview) return null
    return { ...preview, files: acceptedPreviewFiles }
  }, [acceptedPreviewFiles, preview])
  const grouped = useMemo(() => {
    return PRIORITIES.map((priority) => ({
      priority,
      items: keyedFindings.filter((item) => item.finding.priority === priority),
    }))
  }, [keyedFindings])

  function setFindingItems(items: LintFinding[]) {
    setFindings(items)
    const selected = new Set<string>()
    items.forEach((finding, index) => {
      if (!SUGGESTION_KINDS.has(finding.kind)) selected.add(findingKey(finding, index))
    })
    setSelectedFindingKeys(selected)
  }

  function toggleFindingSelection(key: string) {
    setSelectedFindingKeys((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function selectAllActionable() {
    setSelectedFindingKeys(new Set(actionable.map((item) => item.key)))
  }

  function clearSelection() {
    setSelectedFindingKeys(new Set())
  }

  function togglePreviewFile(path: string) {
    setOpenPreviewFiles((current) => {
      const next = new Set(current)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  function togglePreviewAcceptance(path: string) {
    setAcceptedPreviewPaths((current) => {
      const next = new Set(current)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  async function startLint() {
    if (running) return
    setFindingItems([])
    setReport('')
    setError('')
    setPreview(null)
    setPreviewIssuesByFile({})
    setOpenPreviewFiles(new Set())
    setAcceptedPreviewPaths(new Set())
    setOperation('checking')
    setStatus('正在检查...')
    try {
      await runLint(token, (event: LintEvent) => {
        if (event.type === 'progress') {
          setStatus(`正在检查... 已发现 ${event.count} 个问题`)
        } else if (event.type === 'finding') {
          setFindings((items) => {
            const next = [...items, event.finding]
            if (!SUGGESTION_KINDS.has(event.finding.kind)) {
              const key = findingKey(event.finding, next.length - 1)
              setSelectedFindingKeys((current) => new Set(current).add(key))
            }
            return next
          })
        } else if (event.type === 'done') {
          setReport(event.report)
          setStatus(`检查完成: ${event.count} 个发现`)
        } else if (event.type === 'error') {
          setError(event.message)
        }
      })
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '检查失败')
    } finally {
      setOperation('idle')
    }
  }

  async function autoFix() {
    if (running) return
    if (selectedFindings.length === 0) {
      setStatus('请先选择要自动修复的问题')
      return
    }
    setOperation('fixing')
    setError('')
    setPreview(null)
    setPreviewIssuesByFile({})
    setOpenPreviewFiles(new Set())
    setAcceptedPreviewPaths(new Set())
    setStatus('正在自动修复选中项...')
    try {
      const payload = await previewLintFix(token, selectedFindings)
      setFindingItems(payload.findings)
      setPreview(payload.preview)
      if (payload.preview) {
        setPreviewIssuesByFile(buildPreviewIssuesByFile(payload.preview, selectedFindings))
        setAcceptedPreviewPaths(new Set(payload.preview.files.map((file) => file.path)))
        setOpenPreviewFiles(new Set(payload.preview.files.map((file) => file.path)))
      }
      if (payload.preview && payload.preview.files.length > 0) {
        setStatus(`自动修复 ${payload.fixed} 项；已生成大模型修复预览`)
      } else if (payload.llm_error) {
        setStatus(`自动修复 ${payload.fixed} 项；大模型修复预览失败：${payload.llm_error}`)
      } else if (payload.llm_available) {
        setStatus(`自动修复 ${payload.fixed} 项；大模型没有生成可应用预览`)
      } else {
        setStatus(`自动修复 ${payload.fixed} 项；未配置 LLM_API_KEY，无法生成大模型预览`)
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '修复失败')
    } finally {
      setOperation('idle')
    }
  }

  async function applyPreview() {
    if (running || !acceptedPreview || acceptedPreview.files.length === 0) return
    setOperation('applying')
    setError('')
    setStatus('正在应用修复预览...')
    try {
      const payload = await applyLintFixPreview(token, acceptedPreview)
      setFindingItems(payload.findings)
      setPreview(null)
      setPreviewIssuesByFile({})
      setOpenPreviewFiles(new Set())
      setAcceptedPreviewPaths(new Set())
      setStatus(`已应用大模型修复预览，写入 ${payload.written} 个文件`)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '应用预览失败')
    } finally {
      setOperation('idle')
    }
  }

  async function rebuild() {
    if (running) return
    setOperation('rebuilding')
    setError('')
    setPreview(null)
    setPreviewIssuesByFile({})
    setOpenPreviewFiles(new Set())
    setAcceptedPreviewPaths(new Set())
    setStatus('正在重建索引...')
    try {
      const payload = await rebuildLintIndex(token)
      setFindingItems(payload.findings)
      setStatus('索引已重建，静态检查已刷新')
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '重建失败')
    } finally {
      setOperation('idle')
    }
  }

  return (
    <PanelShell
      active="lint"
      eyebrow="SHEIKAH LINT"
      title="Wiki 体检"
      subtitle={status}
      token={token}
    >
      {error && (
        <Dialog type="sheikah" speaker="Panel" showContinue={false}>
          {error}
          </Dialog>
      )}
      <section className="single-grid">
        <Card variant="sheikah" title="Health Check">
          <div className="action-row top">
            <Button
              variant="sheikah"
              loading={operation === 'checking'}
              disabled={running && operation !== 'checking'}
              onClick={() => void startLint()}
            >
              开始检查
            </Button>
            <Button
              variant="ghost"
              loading={operation === 'fixing'}
              disabled={selectedFindings.length === 0 || running}
              onClick={() => void autoFix()}
            >
              自动修复选中项
            </Button>
            <Button
              variant="ghost"
              loading={operation === 'applying'}
              disabled={acceptedPreviewFiles.length === 0 || running}
              onClick={() => void applyPreview()}
            >
              应用预览
            </Button>
            <Button
              variant="ghost"
              loading={operation === 'rebuilding'}
              disabled={running}
              onClick={() => void rebuild()}
            >
              重建索引
            </Button>
          </div>
          {running && <Loading tip={loadingTip} />}
          {report && <p className="subtitle">报告已保存: {report}</p>}
          {actionable.length > 0 && (
            <div className="lint-selection">
              <span>已选择 {selectedFindings.length}/{actionable.length} 个可处理问题</span>
              <button type="button" onClick={selectAllActionable} disabled={running}>全选</button>
              <button type="button" onClick={clearSelection} disabled={running}>清空</button>
            </div>
          )}
          {preview && preview.files.length > 0 && (
            <section className="lint-group">
              <h2>修复预览</h2>
              {preview.summary && <p>{preview.summary}</p>}
              <p className="subtitle">将应用 {acceptedPreviewFiles.length}/{preview.files.length} 个文件；取消勾选可跳过单个文件。</p>
              {preview.files.map((file) => {
                const accepted = acceptedPreviewPaths.has(file.path)
                const rows = buildSideBySideDiff(file.original, file.updated)
                return (
                  <article className={`finding info ${accepted ? '' : 'skipped'}`} key={file.path}>
                    <div className="lint-preview-head">
                      <div>
                        <p className="result-name">{file.path}</p>
                        <p className="subtitle">{accepted ? '将应用此文件' : '已跳过此文件'}</p>
                      </div>
                      <label className="lint-accept">
                        <input
                          type="checkbox"
                          checked={accepted}
                          disabled={running}
                          onChange={() => togglePreviewAcceptance(file.path)}
                        />
                        接受此文件
                      </label>
                      <button type="button" className="diff-toggle" onClick={() => togglePreviewFile(file.path)}>
                        {openPreviewFiles.has(file.path) ? '收起 diff' : '查看 diff'}
                      </button>
                    </div>
                    <div className="lint-file-issues">
                      <p className="subtitle">原体检问题</p>
                      {(previewIssuesByFile[file.path] ?? []).length === 0 && <p className="empty">没有直接匹配到该文件的问题</p>}
                      {(previewIssuesByFile[file.path] ?? []).map((issue, index) => (
                        <p className="subtitle" key={`${issue.kind}-${issue.location}-${index}`}>
                          [{issue.kind}] {issue.message}{issue.suggestion ? ` → ${issue.suggestion}` : ''}
                        </p>
                      ))}
                    </div>
                    {file.issues.length > 0 && <p className="subtitle">模型标记: {file.issues.join(', ')}</p>}
                    {openPreviewFiles.has(file.path) ? (
                      <div className="side-by-side-diff">
                        <div className="diff-pane source">
                          <div className="diff-pane-title">源文件</div>
                          <pre>
                            {rows.map((row, index) => (
                              <span className={`diff-row ${row.kind}`} key={`source-${file.path}-${index}`}>
                                <span className="diff-line-no">{row.oldLine ?? ''}</span>
                                <span className="diff-code">{row.oldText || ' '}</span>
                              </span>
                            ))}
                          </pre>
                        </div>
                        <div className="diff-pane updated">
                          <div className="diff-pane-title">新文件</div>
                          <pre>
                            {rows.map((row, index) => (
                              <span className={`diff-row ${row.kind}`} key={`updated-${file.path}-${index}`}>
                                <span className="diff-line-no">{row.newLine ?? ''}</span>
                                <span className="diff-code">{row.newText || ' '}</span>
                              </span>
                            ))}
                          </pre>
                        </div>
                      </div>
                    ) : (
                      <p className="subtitle">点击“查看 diff”对比修改前后内容</p>
                    )}
                  </article>
                )
              })}
            </section>
          )}
          <div className="lint-groups">
            {grouped.map((group) => (
              <section key={group.priority} className="lint-group">
                <h2>{group.priority}</h2>
                {group.items.length === 0 && <p className="empty">没有发现</p>}
                {group.items.map(({ finding, key, actionable: canSelect }) => (
                  <article className={`finding ${finding.severity}`} key={key}>
                    {canSelect && (
                      <label className="lint-select">
                        <input
                          type="checkbox"
                          checked={selectedFindingKeys.has(key)}
                          disabled={running}
                          onChange={() => toggleFindingSelection(key)}
                        />
                        自动修复此项
                      </label>
                    )}
                    <p className="result-name">[{finding.kind}] {finding.location}</p>
                    <p>{finding.message}</p>
                    {finding.suggestion && <p className="subtitle">{finding.suggestion}</p>}
                    <p className="subtitle">自动处理：点击自动修复生成预览，确认后再应用</p>
                  </article>
                ))}
              </section>
            ))}
          </div>
        </Card>
      </section>
    </PanelShell>
  )
}
