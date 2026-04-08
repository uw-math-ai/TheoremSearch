import { StrictMode, useState, useEffect, useCallback } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import GalaxyApp from './GalaxyApp.jsx'

function getRoute() {
  const path = window.location.pathname
  if (path === '/galaxy') return { view: 'galaxy', paperId: null }
  const m = path.match(/^\/paper\/(.+)$/)
  if (m) return { view: 'graph', paperId: decodeURIComponent(m[1]) }
  return { view: 'graph', paperId: null }
}

function Root() {
  const [route, setRoute] = useState(getRoute)

  useEffect(() => {
    const onPop = () => setRoute(getRoute())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const navigate = useCallback((path) => {
    history.pushState(null, '', path)
    setRoute(getRoute())
  }, [])

  // Called by App after a successful paper fetch; updates URL without re-mounting App
  const onPaperFetched = useCallback((externalId) => {
    const path = `/paper/${encodeURIComponent(externalId)}`
    if (window.location.pathname !== path) {
      history.pushState(null, '', path)
      setRoute({ view: 'graph', paperId: externalId })
    }
  }, [])

  if (route.view === 'galaxy') {
    return (
      <GalaxyApp
        onSwitch={externalId => {
          navigate(externalId ? `/paper/${encodeURIComponent(externalId)}` : '/')
        }}
      />
    )
  }

  return (
    <App
      seedId={route.paperId}
      onPaperFetched={onPaperFetched}
      onSwitch={() => navigate('/galaxy')}
    />
  )
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
