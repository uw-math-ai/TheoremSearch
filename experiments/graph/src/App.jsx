import { useState, useCallback } from 'react'
import GraphView from './GraphView'
import NodePanel from './NodePanel'
import './App.css'

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

  for (const edge of data.dependencies) {
    // Source statement
    const srcId = `stmt:${edge.src_statement_id}`
    if (!nodesMap.has(srcId)) {
      nodesMap.set(srcId, {
        id: srcId,
        type: 'statement',
        name: edge.src_name,
        body: edge.src_body,
        note: edge.src_note,
        proof: edge.src_proof,
      })
    }

    if (edge.dep_statement_id) {
      const depId = `stmt:${edge.dep_statement_id}`
      if (!nodesMap.has(depId)) {
        nodesMap.set(depId, {
          id: depId,
          type: 'statement',
          name: edge.dep_name,
          body: edge.dep_body,
        })
      }
      rawLinks.push({ source: srcId, target: depId, interpaper: edge.interpaper })
    } else if (edge.cited_arxiv_id || edge.cited_paper_key) {
      // Dep is an external paper
      const extKey = edge.cited_arxiv_id || edge.cited_paper_key
      const paperId = `paper:${extKey}`
      if (!nodesMap.has(paperId)) {
        nodesMap.set(paperId, {
          id: paperId,
          type: 'paper',
          isMain: false,
          name: extKey,
          external_id: edge.cited_arxiv_id,
        })
      }
      rawLinks.push({ source: srcId, target: paperId, interpaper: true })
    }
  }

  // Deduplicate links (same source+target pair)
  const seenLinks = new Set()
  const links = rawLinks.filter(l => {
    const key = `${l.source}|${l.target}`
    if (seenLinks.has(key)) return false
    seenLinks.add(key)
    return true
  })

  // Compute degree for node sizing
  const degree = new Map()
  for (const l of links) {
    degree.set(l.source, (degree.get(l.source) || 0) + 1)
    degree.set(l.target, (degree.get(l.target) || 0) + 1)
  }

  const nodes = Array.from(nodesMap.values()).map(n => ({
    ...n,
    degree: degree.get(n.id) || 0,
  }))

  return { nodes, links }
}

export default function App({ onSwitch }) {
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [graph, setGraph] = useState(null)
  const [selected, setSelected] = useState(null)

  const handleFetch = useCallback(async () => {
    const id = input.trim()
    if (!id) return
    setLoading(true)
    setError(null)
    setSelected(null)
    setGraph(null)
    try {
      const res = await fetch(
        `/api/graph?external_id=${encodeURIComponent(id)}`
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

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <span className="brand-name">TheoremSearch</span>
          <span className="brand-sub">Dependency Graph</span>
        </div>

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

        {onSwitch && (
          <button className="nav-btn" onClick={onSwitch}>
            Paper Galaxy →
          </button>
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
      </header>

      <main className="main">
        {error && <div className="error-banner">{error}</div>}

        {graph && (
          <GraphView
            nodes={graph.nodes}
            links={graph.links}
            selected={selected}
            onSelect={setSelected}
          />
        )}

        {!graph && !loading && !error && (
          <div className="empty-state">
            <p>Enter an arXiv ID to visualize its theorem dependency graph.</p>
          </div>
        )}

        {loading && (
          <div className="empty-state">
            <div className="spinner" />
          </div>
        )}
      </main>

      {selected && (
        <NodePanel node={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
