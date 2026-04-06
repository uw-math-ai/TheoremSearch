import { useEffect, useRef } from 'react'
import * as d3 from 'd3'

const STMT_BASE = 6
const PAPER_BASE = 14
const DEGREE_SCALE = 2.2
const STMT_MAX = 18
const PAPER_MAX = 28

function nodeRadius(n) {
  const base = n.type === 'paper' ? PAPER_BASE : STMT_BASE
  const max  = n.type === 'paper' ? PAPER_MAX  : STMT_MAX
  return Math.min(base + n.degree * DEGREE_SCALE, max)
}

function linkStroke(l) {
  if (l.kind === 'membership') return '#475569'
  if (l.kind === 'inter')      return '#b45309'
  return '#1e2a4a'
}
function linkWidth(l) {
  if (l.kind === 'membership') return 0.75
  if (l.kind === 'inter')      return 1.5
  return 1
}
function linkDash(l) {
  if (l.kind === 'membership') return '3,4'
  if (l.kind === 'inter')      return '5,3'
  return null
}
function linkOpacity(l) {
  return l.kind === 'membership' ? 0.3 : 0.75
}

export default function GraphView({ nodes, links, selected, onSelect, onNavigate }) {
  const svgRef = useRef(null)

  useEffect(() => {
    if (!svgRef.current || !nodes.length) return

    const el = svgRef.current
    const width = el.clientWidth
    const height = el.clientHeight

    const nodeData = nodes.map(n => ({ ...n }))
    const linkData = links.map(l => ({ ...l }))

    d3.select(el).selectAll('*').remove()

    const svg = d3.select(el)
    svg.on('click', () => onSelect(null))

    const g = svg.append('g')
    svg.call(
      d3.zoom()
        .scaleExtent([0.08, 5])
        .on('zoom', event => g.attr('transform', event.transform))
    )

    // ── Defs ──────────────────────────────────────────────
    const defs = svg.append('defs')

    const filter = defs.append('filter').attr('id', 'glow')
    filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur')
    const feMerge = filter.append('feMerge')
    feMerge.append('feMergeNode').attr('in', 'coloredBlur')
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic')

    for (const [id, color] of [['arrow-intra', '#1e2a4a'], ['arrow-inter', '#b45309']]) {
      defs.append('marker')
        .attr('id', id)
        .attr('viewBox', '0 -4 8 8')
        .attr('refX', 8).attr('refY', 0)
        .attr('markerWidth', 6).attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path').attr('d', 'M0,-4L8,0L0,4Z')
        .attr('fill', color).attr('fill-opacity', 0.85)
    }

    // ── Force simulation ───────────────────────────────────
    const sim = d3.forceSimulation(nodeData)
      .force('link',
        d3.forceLink(linkData)
          .id(d => d.id)
          .distance(d => {
            if (d.kind === 'membership') return 100
            const either = d.source.type === 'paper' || d.target.type === 'paper'
            return either ? 160 : 90
          })
          .strength(d => d.kind === 'membership' ? 0.15 : 0.35)
      )
      .force('charge',
        d3.forceManyBody().strength(d => d.type === 'paper' ? -500 : -180)
      )
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide().radius(d => nodeRadius(d) + 10).strength(0.7))

    // ── Edges ──────────────────────────────────────────────
    // Membership links drawn first (underneath)
    const memberLink = g.append('g')
      .attr('class', 'membership-links')
      .selectAll('path')
      .data(linkData.filter(l => l.kind === 'membership'))
      .join('path')
      .attr('fill', 'none')
      .attr('stroke', '#475569')
      .attr('stroke-width', 0.75)
      .attr('stroke-dasharray', '3,4')
      .attr('stroke-opacity', 0.3)

    const depLink = g.append('g')
      .attr('class', 'dep-links')
      .selectAll('path')
      .data(linkData.filter(l => l.kind !== 'membership'))
      .join('path')
      .attr('fill', 'none')
      .attr('stroke', l => linkStroke(l))
      .attr('stroke-width', l => linkWidth(l))
      .attr('stroke-dasharray', l => linkDash(l))
      .attr('stroke-opacity', 0.75)
      .attr('marker-end', l => `url(#${l.kind === 'inter' ? 'arrow-inter' : 'arrow-intra'})`)

    // ── Nodes ──────────────────────────────────────────────
    const node = g.append('g')
      .attr('class', 'nodes')
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
      .attr('fill', d => {
        if (d.type === 'paper') return d.isMain ? '#22c55e' : '#d97706'
        if (d.ghost) return '#475569'
        return '#3b5fd4'
      })
      .attr('fill-opacity', d => {
        if (d.type === 'paper') return 0.92
        if (d.ghost) return 0.45
        return 0.8
      })
      .attr('stroke', d => {
        if (d.isMain) return '#4ade80'
        if (d.type === 'paper') return '#fbbf24'
        if (d.ghost) return '#64748b'
        return '#6c8aff'
      })
      .attr('stroke-width', 1.5)

    // Labels: paper nodes always; non-ghost statements with degree ≥ 3
    node.filter(d => d.type === 'paper' || (!d.ghost && d.degree >= 3))
      .append('text')
      .text(d => {
        const raw = d.name || d.id
        return raw.length > 26 ? raw.slice(0, 24) + '…' : raw
      })
      .attr('x', d => nodeRadius(d) + 5)
      .attr('y', '0.35em')
      .attr('font-size', d => d.type === 'paper' ? 11 : 9.5)
      .attr('font-family', 'inherit')
      .attr('fill', '#94a3b8')
      .attr('pointer-events', 'none')

    node.append('title').text(d => d.name || d.id)

    // ── Hover highlight ────────────────────────────────────
    node
      .on('mouseenter', (event, d) => {
        const connectedIds = new Set()
        linkData.forEach(l => {
          if (l.kind === 'membership') return
          if (l.source.id === d.id) connectedIds.add(l.target.id)
          if (l.target.id === d.id) connectedIds.add(l.source.id)
        })

        node.select('circle')
          .attr('fill-opacity', n => {
            if (n.id === d.id || connectedIds.has(n.id)) return 1
            return n.ghost ? 0.12 : 0.15
          })

        depLink.attr('stroke-opacity', l =>
          l.source.id === d.id || l.target.id === d.id ? 1 : 0.05
        )
        memberLink.attr('stroke-opacity', 0.1)
      })
      .on('mouseleave', () => {
        node.select('circle')
          .attr('fill-opacity', n => {
            if (n.type === 'paper') return 0.92
            return n.ghost ? 0.45 : 0.8
          })
        depLink.attr('stroke-opacity', 0.75)
        memberLink.attr('stroke-opacity', 0.3)
      })
      .on('click', (event, d) => {
        event.stopPropagation()
        onSelect(d)
      })
      .on('dblclick', (event, d) => {
        event.stopPropagation()
        if (d.type === 'paper' && d.external_id && onNavigate) onNavigate(d.external_id)
      })

    // ── Tick ──────────────────────────────────────────────
    function edgePath(d) {
      const dx = d.target.x - d.source.x
      const dy = d.target.y - d.source.y
      const dist = Math.sqrt(dx * dx + dy * dy) || 1
      const r = nodeRadius(d.target)
      const tx = d.target.x - (dx / dist) * r
      const ty = d.target.y - (dy / dist) * r
      return `M${d.source.x},${d.source.y}L${tx},${ty}`
    }

    sim.on('tick', () => {
      memberLink.attr('d', edgePath)
      depLink.attr('d', edgePath)
      node.attr('transform', d => `translate(${d.x},${d.y})`)
    })

    return () => sim.stop()
  }, [nodes, links]) // eslint-disable-line react-hooks/exhaustive-deps

  // Highlight selected node without re-running simulation
  useEffect(() => {
    if (!svgRef.current) return
    d3.select(svgRef.current)
      .selectAll('.node circle')
      .attr('stroke', d => {
        if (selected?.id === d.id) return '#ffffff'
        if (d.isMain) return '#4ade80'
        if (d.type === 'paper') return '#fbbf24'
        if (d.ghost) return '#64748b'
        return '#6c8aff'
      })
      .attr('stroke-width', d => selected?.id === d.id ? 2.5 : 1.5)
      .style('filter', d => selected?.id === d.id ? 'url(#glow)' : null)
  }, [selected])

  return <svg ref={svgRef} className="graph-svg" />
}
