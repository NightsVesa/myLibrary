type LibraryGroupLike<T> = {
  kind: string
  label: string
  items: T[]
}

export type CollapsibleLibraryGroup<T> = LibraryGroupLike<T> & {
  displayLabel: string
  count: number
  collapsed: boolean
}

const WIKI_KIND_LABELS: Record<string, string> = {
  source: '来源',
  concept: '概念',
  entity: '实体',
}

function compareTagLabels(left: string, right: string) {
  const leftAscii = /^[\x00-\x7F]/.test(left)
  const rightAscii = /^[\x00-\x7F]/.test(right)
  if (leftAscii !== rightAscii) return leftAscii ? -1 : 1
  return left.localeCompare(right, undefined, { sensitivity: 'base' })
}

export function buildCollapsibleGroups<T>(
  groups: Array<LibraryGroupLike<T>>,
  collapsedKinds: ReadonlySet<string>,
): Array<CollapsibleLibraryGroup<T>> {
  return groups
    .filter((group) => group.items.length > 0)
    .map((group) => ({
      ...group,
      displayLabel: WIKI_KIND_LABELS[group.kind] ?? group.label,
      count: group.items.length,
      collapsed: collapsedKinds.has(group.kind),
    }))
}

type TaggedItem = {
  tags?: string[]
}

export function buildTagGroups<T extends TaggedItem>(
  items: T[],
  collapsedKinds: ReadonlySet<string>,
): Array<CollapsibleLibraryGroup<T>> {
  const groups = new Map<string, { label: string; items: T[] }>()
  for (const item of items) {
    const seen = new Set<string>()
    for (const rawTag of item.tags ?? []) {
      const tag = String(rawTag).trim()
      if (!tag) continue
      const folded = tag.toLocaleLowerCase()
      if (seen.has(folded)) continue
      seen.add(folded)
      const group = groups.get(folded) ?? { label: tag, items: [] }
      group.items.push(item)
      groups.set(folded, group)
    }
  }
  return Array.from(groups.entries())
    .sort((left, right) => compareTagLabels(left[1].label, right[1].label))
    .map(([folded, group]) => {
      const kind = `tag:${folded}`
      return {
        kind,
        label: group.label,
        displayLabel: `#${group.label}`,
        items: group.items,
        count: group.items.length,
        collapsed: collapsedKinds.has(kind),
      }
    })
}
