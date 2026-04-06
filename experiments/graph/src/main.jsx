import { StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import GalaxyApp from './GalaxyApp.jsx'

function Root() {
  const [view, setView] = useState('graph')
  if (view === 'galaxy') return <GalaxyApp onSwitch={() => setView('graph')} />
  return <App onSwitch={() => setView('galaxy')} />
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
