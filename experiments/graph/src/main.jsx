import { StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import GalaxyApp from './GalaxyApp.jsx'

function Root() {
  const [view, setView] = useState('graph')
  const [seedId, setSeedId] = useState(null)

  if (view === 'galaxy') {
    return (
      <GalaxyApp
        onSwitch={externalId => {
          setSeedId(externalId || null)
          setView('graph')
        }}
      />
    )
  }
  return (
    <App
      seedId={seedId}
      onSwitch={() => { setSeedId(null); setView('galaxy') }}
    />
  )
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
