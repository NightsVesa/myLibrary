import type { ReactNode } from 'react'
import { parseWikilinkTarget, resolveWikiPageLink } from './wikiLinks'

type WikiLinkHandler = (path: string) => void

type MarkdownContext = {
  currentPath?: string
  onWikiLink?: WikiLinkHandler
}

function renderLink(label: string, target: string, key: string, context: MarkdownContext): ReactNode {
  const wikiPath = resolveWikiPageLink(context.currentPath ?? '', target)
  if (wikiPath && context.onWikiLink) {
    return (
      <button
        className="markdown-link"
        key={key}
        onClick={() => context.onWikiLink?.(wikiPath)}
        type="button"
      >
        {label || wikiPath}
      </button>
    )
  }
  return (
    <a href={target} key={key} rel="noreferrer" target="_blank">
      {label || target}
    </a>
  )
}

export function renderInlineMarkdown(text: string, context: MarkdownContext = {}): ReactNode[] {
  const nodes: ReactNode[] = []
  const pattern = /(\[\[([^\]]+)\]\])|(!?\[([^\]]*)\]\(([^)]+)\))|(`([^`]+)`)|(\*\*([^*]+)\*\*)/g
  let cursor = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index))
    if (match[1]) {
      const parsed = parseWikilinkTarget(match[2])
      nodes.push(renderLink(parsed.label, parsed.target, `${match.index}-wikilink`, context))
    } else if (match[3]?.startsWith('!')) {
      nodes.push(<span className="markdown-image-missing" key={`${match.index}-img`}>{match[4]}</span>)
    } else if (match[3]) {
      nodes.push(renderLink(match[4], match[5], `${match.index}-link`, context))
    } else if (match[6]) {
      nodes.push(<code key={`${match.index}-code`}>{match[7]}</code>)
    } else if (match[8]) {
      nodes.push(<strong key={`${match.index}-strong`}>{match[9]}</strong>)
    }
    cursor = match.index + match[0].length
  }
  if (cursor < text.length) nodes.push(text.slice(cursor))
  return nodes
}

export function MarkdownInline({ text, currentPath = '', onWikiLink }: {
  text: string
  currentPath?: string
  onWikiLink?: WikiLinkHandler
}) {
  return <>{renderInlineMarkdown(text, { currentPath, onWikiLink })}</>
}

export function MarkdownBlocks({ source, currentPath = '', onWikiLink }: {
  source: string
  currentPath?: string
  onWikiLink?: WikiLinkHandler
}) {
  const lines = source.split(/\r?\n/)
  const blocks: ReactNode[] = []
  let code: string[] = []
  let inCode = false
  let list: ReactNode[] = []
  const context = { currentPath, onWikiLink }

  function flushList() {
    if (list.length) {
      blocks.push(<ul key={`list-${blocks.length}`}>{list}</ul>)
      list = []
    }
  }

  function flushCode() {
    if (inCode) {
      blocks.push(<pre className="markdown-code-block" key={`code-${blocks.length}`}>{code.join('\n')}</pre>)
      code = []
      inCode = false
    }
  }

  lines.forEach((line, index) => {
    if (line.startsWith('```')) {
      if (inCode) {
        flushCode()
      } else {
        flushList()
        inCode = true
        code = []
      }
      return
    }
    if (inCode) {
      code.push(line)
      return
    }
    if (!line.trim()) {
      flushList()
      return
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line)
    if (heading) {
      flushList()
      const level = heading[1].length
      const Tag = `h${level}` as keyof JSX.IntrinsicElements
      blocks.push(<Tag key={`h-${index}`}>{renderInlineMarkdown(heading[2], context)}</Tag>)
      return
    }
    const item = /^\s*[-*]\s+(.+)$/.exec(line)
    if (item) {
      list.push(<li key={`li-${index}`}>{renderInlineMarkdown(item[1], context)}</li>)
      return
    }
    flushList()
    if (line.startsWith('>')) {
      blocks.push(<blockquote key={`quote-${index}`}>{renderInlineMarkdown(line.replace(/^>\s?/, ''), context)}</blockquote>)
    } else if (/^---+$/.test(line.trim())) {
      blocks.push(<hr key={`hr-${index}`} />)
    } else {
      blocks.push(<p key={`p-${index}`}>{renderInlineMarkdown(line, context)}</p>)
    }
  })
  flushList()
  flushCode()
  return <div className="markdown-rendered">{blocks}</div>
}
