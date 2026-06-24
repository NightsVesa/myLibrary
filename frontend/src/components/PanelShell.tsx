import { ReactNode } from 'react'
import {
  Button,
  SheikahBackground,
  SheikahScanlines,
  SheikahSymbol,
} from 'zelda-hyrule-ui'
import { navigatePanel } from '../api'

const NAV_ITEMS = [
  { route: 'input', label: '输入' },
  { route: 'upload', label: '上传' },
  { route: 'search', label: '搜索' },
  { route: 'chat', label: '问答' },
  { route: 'graph', label: '图谱' },
  { route: 'lint', label: '体检' },
]

type PanelShellProps = {
  active: string
  eyebrow?: string
  title: string
  subtitle?: string
  token: string
  children: ReactNode
}

export function PanelShell({
  active,
  title,
  token,
  children,
}: PanelShellProps) {
  return (
    <div className="app-shell">
      <div className="app-titlebar">
        <div className="titlebar-brand">
          <SheikahSymbol size={30} />
          <div>
            <span className="titlebar-app">myLibrary</span>
            <span className="titlebar-panel">{title}</span>
          </div>
        </div>
        <div className="titlebar-lines" aria-hidden="true" />
        <nav className="panel-nav" aria-label="Panel navigation">
          {NAV_ITEMS.map((item) => (
            <Button
              key={item.route}
              variant={item.route === active ? 'sheikah' : 'ghost'}
              size="small"
              onClick={() => navigatePanel(item.route, token)}
            >
              {item.label}
            </Button>
          ))}
        </nav>
      </div>
      <SheikahBackground color="darkBlue">
        <SheikahScanlines opacity={0.06} />
        <main className="panel">
          {children}
        </main>
      </SheikahBackground>
    </div>
  )
}
