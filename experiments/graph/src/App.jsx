import { useState, useCallback, useEffect, useRef } from 'react'
import GraphView from './GraphView'
import NodePanel from './NodePanel'
import './App.css'

function buildGraphFromJSON(data) {
  const nodesMap = new Map()
  const rawLinks = []

  const paperId = `paper:${data.arxiv_id}`
  nodesMap.set(paperId, {
    id: paperId,
    type: 'paper',
    isMain: true,
    name: data.arxiv_id,
    external_id: data.arxiv_id,
  })

  for (const dep of data.dependencies) {
    const srcId = `stmt:${dep.src_name}`
    if (!nodesMap.has(srcId)) {
      nodesMap.set(srcId, {
        id: srcId,
        type: 'statement',
        ghost: false,
        name: dep.src_name,
        body: dep.src_body,
        note: dep.src_note,
        proof: dep.src_proof,
      })
      rawLinks.push({ source: paperId, target: srcId, kind: 'membership' })
    }

    if (dep.interpaper) {
      const extKey = dep.cited_arxiv_id ?? dep.cited_paper_key
      if (extKey) {
        const extPaperId = `paper:${extKey}`
        if (!nodesMap.has(extPaperId)) {
          nodesMap.set(extPaperId, {
            id: extPaperId,
            type: 'paper',
            isMain: false,
            name: extKey,
            external_id: dep.cited_arxiv_id,
          })
        }
        rawLinks.push({ source: srcId, target: extPaperId, kind: 'inter' })
      }
    } else {
      const depId = `stmt:${dep.dep_name}`
      if (!nodesMap.has(depId)) {
        nodesMap.set(depId, {
          id: depId,
          type: 'statement',
          ghost: false,
          name: dep.dep_name,
          body: dep.dep_body,
        })
        rawLinks.push({ source: paperId, target: depId, kind: 'membership' })
      }
      rawLinks.push({ source: srcId, target: depId, kind: 'intra' })
    }
  }

  const seenLinks = new Set()
  const links = rawLinks.filter(l => {
    const key = `${l.source}|${l.target}`
    if (seenLinks.has(key)) return false
    seenLinks.add(key)
    return true
  })

  const degree = new Map()
  for (const l of links) {
    if (l.kind === 'membership') continue
    degree.set(l.source, (degree.get(l.source) || 0) + 1)
    degree.set(l.target, (degree.get(l.target) || 0) + 1)
  }

  const nodes = Array.from(nodesMap.values()).map(n => ({
    ...n,
    degree: degree.get(n.id) || 0,
  }))

  return { nodes, links }
}

function buildGraph(data) {
  const nodesMap = new Map()

  // Main paper node
  const mainPaperId = `paper:${data.paper.paper_id}`
  nodesMap.set(mainPaperId, {
    id: mainPaperId,
    type: 'paper',
    isMain: true,
    name: data.paper.title,
    external_id: data.paper.external_id,
    url: data.paper.url,
  })

  const rawLinks = []

  // Collect statement IDs that participate in dep edges (as src or dep)
  const stmtsInDeps = new Set()
  for (const edge of data.dependencies) {
    stmtsInDeps.add(edge.src_statement_id)
    if (edge.dep_statement_id) stmtsInDeps.add(edge.dep_statement_id)
  }

  // Add ALL statements for this paper; ghost if not in any dep edge
  for (const stmt of data.statements) {
    const stmtId = `stmt:${stmt.statement_id}`
    nodesMap.set(stmtId, {
      id: stmtId,
      type: 'statement',
      ghost: !stmtsInDeps.has(stmt.statement_id),
      name: stmt.name,
      body: stmt.body,
      note: stmt.note,
      proof: stmt.proof,
    })
    rawLinks.push({ source: mainPaperId, target: stmtId, kind: 'membership' })
  }

  // Dep edges
  for (const edge of data.dependencies) {
    const srcId = `stmt:${edge.src_statement_id}`
    // Ensure src node exists (may be missing if not in data.statements, e.g. external)
    if (!nodesMap.has(srcId)) {
      nodesMap.set(srcId, {
        id: srcId,
        type: 'statement',
        ghost: false,
        name: edge.src_name,
        body: edge.src_body,
        note: edge.src_note,
        proof: edge.src_proof,
      })
      rawLinks.push({ source: mainPaperId, target: srcId, kind: 'membership' })
    }

    if (edge.dep_statement_id) {
      const depId = `stmt:${edge.dep_statement_id}`
      if (!nodesMap.has(depId)) {
        nodesMap.set(depId, {
          id: depId,
          type: 'statement',
          ghost: false,
          name: edge.dep_name,
          body: edge.dep_body,
        })
      }
      rawLinks.push({ source: srcId, target: depId, kind: edge.interpaper ? 'inter' : 'intra' })
    } else if (edge.dep_paper_ext_id || edge.cited_paper_key) {
      const extKey = edge.dep_paper_ext_id || edge.cited_paper_key
      const paperId = `paper:${extKey}`
      if (!nodesMap.has(paperId)) {
        nodesMap.set(paperId, {
          id: paperId,
          type: 'paper',
          isMain: false,
          name: extKey,
          external_id: edge.dep_paper_ext_id,
        })
      }
      rawLinks.push({ source: srcId, target: paperId, kind: 'inter' })
    }
  }

  // Deduplicate links
  const seenLinks = new Set()
  const links = rawLinks.filter(l => {
    const key = `${l.source}|${l.target}`
    if (seenLinks.has(key)) return false
    seenLinks.add(key)
    return true
  })

  // Degree counts only dep edges (not membership) for node sizing
  const degree = new Map()
  for (const l of links) {
    if (l.kind === 'membership') continue
    degree.set(l.source, (degree.get(l.source) || 0) + 1)
    degree.set(l.target, (degree.get(l.target) || 0) + 1)
  }

  const nodes = Array.from(nodesMap.values()).map(n => ({
    ...n,
    degree: degree.get(n.id) || 0,
  }))

  return { nodes, links }
}

export default function App({ onSwitch, seedId }) {
  const [mode, setMode] = useState('arxiv') // 'arxiv' | 'json'
  const [input, setInput] = useState(seedId || '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [graph, setGraph] = useState(null)
  const [selected, setSelected] = useState(null)
  const fileInputRef = useRef(null)

  const resetGraph = () => {
    setGraph(null)
    setError(null)
    setSelected(null)
  }

  const handleModeSwitch = (newMode) => {
    if (newMode === mode) return
    setMode(newMode)
    resetGraph()
  }

  // Auto-fetch when arriving from galaxy with a pre-selected paper
  const handleFetch = useCallback(async (overrideId) => {
    const id = (typeof overrideId === 'string' ? overrideId : input).trim()
    if (!id) return
    setLoading(true)
    setError(null)
    setSelected(null)
    setGraph(null)
    try {
      const res = await fetch(
        `${__API_BASE__}/graph?external_id=${encodeURIComponent(id)}`
      )
      if (!res.ok) {
        const msg = res.status === 404
          ? `No paper found for "${id}"`
          : `API error ${res.status}`
        throw new Error(msg)
      }
      const data = await res.json()
      setGraph(buildGraph(data))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [input])

  const handleFileUpload = useCallback((e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    setSelected(null)
    setGraph(null)
    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const data = JSON.parse(ev.target.result)
        setGraph(buildGraphFromJSON(data))
      } catch {
        setError('Invalid JSON file.')
      }
    }
    reader.readAsText(file)
    // Reset so the same file can be re-uploaded
    e.target.value = ''
  }, [])

  useEffect(() => {
    if (seedId) handleFetch(seedId)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <span className="brand-name">TheoremSearch Graph</span>
        </div>

        <div className="mode-toggle">
          <button
            className={`mode-btn${mode === 'arxiv' ? ' active' : ''}`}
            onClick={() => handleModeSwitch('arxiv')}
          >
            arXiv ID
          </button>
          <button
            className={`mode-btn${mode === 'json' ? ' active' : ''}`}
            onClick={() => handleModeSwitch('json')}
          >
            JSON
          </button>
        </div>

        {mode === 'arxiv' ? (
          <div className="search-bar">
            <input
              className="search-input"
              type="text"
              placeholder="arXiv ID — e.g. 2402.06935"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleFetch()}
              disabled={loading}
            />
            <button className="search-btn" onClick={handleFetch} disabled={loading}>
              {loading ? 'Loading…' : 'Graph'}
            </button>
          </div>
        ) : (
          <div className="search-bar">
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,application/json"
              style={{ display: 'none' }}
              onChange={handleFileUpload}
            />
            <button
              className="search-btn"
              onClick={() => fileInputRef.current?.click()}
            >
              Upload JSON
            </button>
          </div>
        )}

        {onSwitch && (
          <button className="nav-btn" onClick={onSwitch}>
            Paper Galaxy →
          </button>
        )}
      </header>

      <main className="main">
        {error && <div className="error-banner">{error}</div>}

        {graph && (
          <GraphView
            nodes={graph.nodes}
            links={graph.links}
            selected={selected}
            onSelect={setSelected}
            onNavigate={mode === 'arxiv' ? handleFetch : undefined}
          />
        )}

        {!graph && !loading && !error && (
          <div className="empty-state">
            {mode === 'arxiv'
              ? <p>Enter an arXiv ID to visualize its theorem dependency graph.</p>
              : <p>Upload a JSON file to visualize its theorem dependency graph.</p>
            }
          </div>
        )}

        {loading && (
          <div className="empty-state">
            <div className="spinner" />
          </div>
        )}

        <div className="legend">
          <span className="legend-item">
            <span className="legend-dot stmt" /> Statement
          </span>
          <span className="legend-item">
            <span className="legend-dot paper" /> Paper
          </span>
          <span className="legend-item">
            <span className="legend-line intra" /> Intra-paper dep
          </span>
          <span className="legend-item">
            <span className="legend-line inter" /> Inter-paper dep
          </span>
        </div>
      </main>

      {selected && (
        <NodePanel
          node={selected}
          onClose={() => setSelected(null)}
          onNavigate={selected.type === 'paper' ? handleFetch : undefined}
        />
      )}
    </div>
  )
}
