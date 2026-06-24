const WIKI_ROOTS = new Set(['sources', 'entities', 'concepts', 'synthesis'])
const EXTERNAL_SCHEME = /^[a-z][a-z0-9+.-]*:/i

export function parseWikilinkTarget(raw: string): { target: string; label: string } {
  const [target, ...labelParts] = raw.split('|')
  const cleanTarget = target.trim()
  const label = labelParts.join('|').trim() || cleanTarget
  return { target: cleanTarget, label }
}

function stripAnchorAndQuery(target: string): string {
  return target.split('#', 1)[0].split('?', 1)[0].trim()
}

function normalizePath(path: string): string | null {
  const out: string[] = []
  for (const part of path.replace(/\\/g, '/').split('/')) {
    if (!part || part === '.') continue
    if (part === '..') {
      if (out.length === 0) return null
      out.pop()
    } else {
      out.push(part)
    }
  }
  if (out.length < 2 || !WIKI_ROOTS.has(out[0]) || !out[out.length - 1].endsWith('.md')) {
    return null
  }
  return out.join('/')
}

export function resolveWikiPageLink(currentPath: string, rawTarget: string): string | null {
  const target = stripAnchorAndQuery(rawTarget)
  if (!target || EXTERNAL_SCHEME.test(target) || target.startsWith('#')) return null

  const normalizedTarget = target.replace(/^\/+/, '').replace(/\\/g, '/')
  const first = normalizedTarget.split('/', 1)[0]
  if (WIKI_ROOTS.has(first)) {
    return normalizePath(normalizedTarget)
  }

  const current = currentPath.replace(/\\/g, '/')
  const baseDir = current.includes('/') ? current.slice(0, current.lastIndexOf('/')) : ''
  return normalizePath(baseDir ? `${baseDir}/${normalizedTarget}` : normalizedTarget)
}
