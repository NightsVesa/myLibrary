import { useEffect, useMemo, useState } from 'react'
import { Dialog } from 'zelda-hyrule-ui'
import { currentRoute, navigatePanel, panelToken, pollPanelRouteCommand } from './api'
import { ChatPage } from './pages/ChatPage'
import { GraphPage } from './pages/GraphPage'
import { IngestPage } from './pages/IngestPage'
import { InputPage } from './pages/InputPage'
import { LintPage } from './pages/LintPage'
import { SearchPage } from './pages/SearchPage'
import { UploadPage } from './pages/UploadPage'

const ROUTES = ['/input', '/upload', '/search', '/chat', '/graph', '/lint', '/ingest']

export default function App() {
  const token = useMemo(panelToken, [])
  const [route, setRoute] = useState(currentRoute())

  useEffect(() => {
    const onHashChange = () => setRoute(currentRoute())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  useEffect(() => {
    if (!token) return
    let stopped = false
    const poll = async () => {
      try {
        const command = await pollPanelRouteCommand(token)
        if (!stopped && command.route && ROUTES.includes(`/${command.route}`)) {
          navigatePanel(command.route, token, command.params)
        }
      } catch {
        // Route polling is best-effort; page APIs surface their own errors.
      }
    }
    const timer = window.setInterval(poll, 250)
    void poll()
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [token])

  if (!token) {
    return (
      <div className="app-shell missing-token">
        <Dialog type="sheikah" speaker="Panel" showContinue={false}>
          缺少面板令牌
        </Dialog>
      </div>
    )
  }

  if (route === 'input') return <InputPage token={token} />
  if (route === 'upload') return <UploadPage token={token} />
  if (route === 'chat') return <ChatPage token={token} />
  if (route === 'graph') return <GraphPage token={token} />
  if (route === 'lint') return <LintPage token={token} />
  if (route === 'ingest') return <IngestPage token={token} />
  return <SearchPage token={token} />
}

export { ROUTES }
