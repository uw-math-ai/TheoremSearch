import { useEffect, useRef, useState, useCallback } from 'react'
import * as d3 from 'd3'
import NodePanel from './NodePanel'
import './App.css'

const NODE_R_MIN = 4
const NODE_R_MAX = 16
const NODE_R_SCALE = 0.4

function nodeRadius(d) {
  return Math.min(NODE_R_MIN + (d.statement_count || 0) * NODE_R_SCALE, NODE_R_MAX)
}

export default function GalaxyApp({ onSwitch }) {
  const svgRef = useRef(null)
  const [papers, setPapers] = useState([])
  const [paperLinks, setPaperLinks] = useState([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [active, setActive] = useState(null)   // { paper_id, title, external_id }
  const simRef = useRef(null)

  // Fetch papers + citation links in parallel
  useEffect(() => {
    Promise.all([
      fetch(`${__API_BASE__}/api/papers`).then(r => r.json()),
      fetch(`${__API_BASE__}/api/paper-links`).then(r => r.json()),
    ])
      .then(([papersData, linksData]) => {
        setPapers(papersData.papers || [])
        setPaperLinks(linksData.links || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  // Build / rebuild galaxy when data changes
  useEffect(() => {
    if (!svgRef.current || !papers.length) return

    const el = svgRef.current
    const width = el.clientWidth
    const height = el.clientHeight

    const nodeData = papers.map(p => ({ ...p }))
    const nodeById = new Map(nodeData.map(n => [n.paper_id, n]))

    // Only keep links where both endpoints are present
    const linkData = paperLinks
      .filter(l => nodeById.has(l.source) && nodeById.has(l.target))
      .map(l => ({ source: l.source, target: l.target }))

    d3.select(el).selectAll('*').remove()

    const svg = d3.select(el)
    svg.on('click', () => setActive(null))

    const g = svg.append('g')
    svg.call(
      d3.zoom()
        .scaleExtent([0.1, 8])
        .on('zoom', event => g.attr('transform', event.transform))
    )

    // Defs: glow + arrowhead
    const defs = svg.append('defs')
    const filter = defs.append('filter').attr('id', 'star-glow')
    filter.append('feGaussianBlur').attr('stdDeviation', '2.5').attr('result', 'coloredBlur')
    const feMerge = filter.append('feMerge')
    feMerge.append('feMergeNode').attr('in', 'coloredBlur')
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic')

    defs.append('marker')
      .attr('id', 'galaxy-arrow')
      .attr('viewBox', '0 -4 8 8')
      .attr('refX', 8)
      .attr('refY', 0)
      .attr('markerWidth', 5)
      .attr('markerHeight', 5)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-4L8,0L0,4Z')
      .attr('fill', '#b45309')
      .attr('fill-opacity', 0.6)

    const sim = d3.forceSimulation(nodeData)
      .force('link',
        d3.forceLink(linkData)
          .id(d => d.paper_id)
          .distance(80)
          .strength(0.15)
      )
      .force('charge', d3.forceManyBody().strength(-40))
      .force('center', d3.forceCenter(width / 2, height / 2).strength(0.08))
      .force('collide', d3.forceCollide(d => nodeRadius(d) + 4).strength(0.6))

    simRef.current = sim

    // Edges (drawn first, so nodes sit on top)
    const link = g.append('g')
      .attr('class', 'galaxy-links')
      .selectAll('path')
      .data(linkData)
      .join('path')
      .attr('fill', 'none')
      .attr('stroke', '#b45309')
      .attr('stroke-width', 0.8)
      .attr('stroke-opacity', 0.35)
      .attr('marker-end', 'url(#galaxy-arrow)')

    const node = g.append('g')
      .selectAll('g')
      .data(nodeData)
      .join('g')
      .attr('class', 'node')
      .style('cursor', 'pointer')
      .call(
        d3.drag()
          .on('start', (event, d) => {
            if (!event.active) sim.alphaTarget(0.3).restart()
            d.fx = d.x; d.fy = d.y
          })
          .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
          .on('end', (event, d) => {
            if (!event.active) sim.alphaTarget(0)
            d.fx = null; d.fy = null
          })
      )

    node.append('circle')
      .attr('r', d => nodeRadius(d))
      .attr('fill', '#f59e0b')
      .attr('fill-opacity', 0.85)
      .attr('stroke', '#fbbf24')
      .attr('stroke-width', 1)

    node.append('title').text(d => `${d.external_id}\n${d.title}`)

    node
      .on('click', (event, d) => {
        event.stopPropagation()
        setActive(d)
        setQuery('')
        setDropdownOpen(false)
      })
      .on('dblclick', (event, d) => {
        event.stopPropagation()
        if (d.external_id) onSwitch(d.external_id)
      })

    sim.on('tick', () => {
      link.attr('d', d => {
        const dx = d.target.x - d.source.x
        const dy = d.target.y - d.source.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const tx = d.target.x - (dx / dist) * nodeRadius(d.target)
        const ty = d.target.y - (dy / dist) * nodeRadius(d.target)
        return `M${d.source.x},${d.source.y}L${tx},${ty}`
      })
      node.attr('transform', d => `translate(${d.x},${d.y})`)
    })

    return () => sim.stop()
  }, [papers, paperLinks])

  // Highlight active node
  useEffect(() => {
    if (!svgRef.current) return
    d3.select(svgRef.current)
      .selectAll('.node circle')
      .attr('fill', d => d.paper_id === active?.paper_id ? '#ffffff' : '#f59e0b')
      .attr('fill-opacity', d => d.paper_id === active?.paper_id ? 1 : 0.85)
      .attr('r', d => d.paper_id === active?.paper_id ? nodeRadius(d) + 3 : nodeRadius(d))
      .style('filter', d => d.paper_id === active?.paper_id ? 'url(#star-glow)' : null)
  }, [active])

  const filtered = query.trim()
    ? papers.filter(p =>
        p.title?.toLowerCase().includes(query.toLowerCase()) ||
        p.external_id?.toLowerCase().includes(query.toLowerCase())
      ).slice(0, 8)
    : []

  const handleSelectPaper = useCallback(paper => {
    setActive(paper)
    setQuery('')
    setDropdownOpen(false)
  }, [])

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <span className="brand-name">TheoremSearch Graph</span>
        </div>

        <div className="galaxy-search">
          <input
            className="search-input"
            type="text"
            placeholder="Search papers…"
            value={query}
            onChange={e => { setQuery(e.target.value); setDropdownOpen(true) }}
            onFocus={() => query && setDropdownOpen(true)}
            onBlur={() => setTimeout(() => setDropdownOpen(false), 150)}
          />
          {dropdownOpen && filtered.length > 0 && (
            <div className="galaxy-dropdown">
              {filtered.map(p => (
                <div
                  key={p.paper_id}
                  className={`galaxy-dropdown-item${active?.paper_id === p.paper_id ? ' active' : ''}`}
                  onMouseDown={() => handleSelectPaper(p)}
                >
                  <span className="galaxy-dropdown-id">{p.external_id}</span>
                  <span className="galaxy-dropdown-title">{p.title}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <button className="nav-btn" onClick={() => onSwitch(null)}>
          ← Back to Graph
        </button>
      </header>

      <main className="main">
        {loading && (
          <div className="empty-state">
            <div className="spinner" />
          </div>
        )}

        <svg ref={svgRef} className="graph-svg" />
      </main>

      {active && (
        <NodePanel
          node={{
            type: 'paper',
            name: active.title,
            external_id: active.external_id,
            degree: active.statement_count || 0,
            isMain: false,
          }}
          onClose={() => setActive(null)}
          onNavigate={id => onSwitch(id)}
        />
      )}
    </div>
  )
}
