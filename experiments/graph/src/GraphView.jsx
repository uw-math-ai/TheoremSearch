import { useEffect, useRef } from 'react'
import * as d3 from 'd3'

const STMT_BASE = 6
const PAPER_BASE = 14
const DEGREE_SCALE = 2.2

function nodeRadius(n) {
  const base = n.type === 'paper' ? PAPER_BASE : STMT_BASE
  return base + n.degree * DEGREE_SCALE
}

export default function GraphView({ nodes, links, selected, onSelect }) {
  const svgRef = useRef(null)

  // Build / rebuild graph when data changes
  useEffect(() => {
    if (!svgRef.current || !nodes.length) return

    const el = svgRef.current
    const width = el.clientWidth
    const height = el.clientHeight

    // Deep-copy so D3 can mutate freely
    const nodeData = nodes.map(n => ({ ...n }))
    const linkData = links.map(l => ({ ...l }))

    // ── Setup ──────────────────────────────────────────────
    d3.select(el).selectAll('*').remove()

    const svg = d3.select(el)

    // Background click → deselect
    svg.on('click', () => onSelect(null))

    // Zoom / pan
    const g = svg.append('g')
    svg.call(
      d3.zoom()
        .scaleExtent([0.08, 5])
        .on('zoom', event => g.attr('transform', event.transform))
    )

    // ── Force simulation ───────────────────────────────────
    const sim = d3.forceSimulation(nodeData)
      .force('link',
        d3.forceLink(linkData)
          .id(d => d.id)
          .distance(d => {
            const either = d.source.type === 'paper' || d.target.type === 'paper'
            return either ? 160 : 90
          })
          .strength(0.35)
      )
      .force('charge',
        d3.forceManyBody().strength(d => d.type === 'paper' ? -500 : -180)
      )
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide().radius(d => nodeRadius(d) + 10).strength(0.7))

    // ── Edges ──────────────────────────────────────────────
    const link = g.append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(linkData)
      .join('line')
      .attr('class', 'edge')
      .attr('stroke', d => d.interpaper ? '#b45309' : '#1e2a4a')
      .attr('stroke-width', d => d.interpaper ? 1.5 : 1)
      .attr('stroke-dasharray', d => d.interpaper ? '5,3' : null)
      .attr('stroke-opacity', 0.75)

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

    // Glow filter
    const defs = svg.append('defs')
    const filter = defs.append('filter').attr('id', 'glow')
    filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur')
    const feMerge = filter.append('feMerge')
    feMerge.append('feMergeNode').attr('in', 'coloredBlur')
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic')

    // Circle
    node.append('circle')
      .attr('r', d => nodeRadius(d))
      .attr('fill', d => {
        if (d.type === 'paper') return d.isMain ? '#f59e0b' : '#d97706'
        return '#3b5fd4'
      })
      .attr('fill-opacity', d => d.type === 'paper' ? 0.92 : 0.8)
      .attr('stroke', d => d.type === 'paper' ? '#fbbf24' : '#6c8aff')
      .attr('stroke-width', 1.5)

    // Label: paper nodes always, statement nodes with degree ≥ 3
    node.filter(d => d.type === 'paper' || d.degree >= 3)
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

    // Native tooltip
    node.append('title').text(d => d.name || d.id)

    // ── Hover highlight ────────────────────────────────────
    node
      .on('mouseenter', (event, d) => {
        const connectedIds = new Set()
        linkData.forEach(l => {
          if (l.source.id === d.id) connectedIds.add(l.target.id)
          if (l.target.id === d.id) connectedIds.add(l.source.id)
        })

        node.select('circle')
          .attr('fill-opacity', n =>
            n.id === d.id || connectedIds.has(n.id) ? 1 : 0.15
          )

        link
          .attr('stroke-opacity', l =>
            l.source.id === d.id || l.target.id === d.id ? 1 : 0.05
          )
      })
      .on('mouseleave', () => {
        node.select('circle')
          .attr('fill-opacity', n => n.type === 'paper' ? 0.92 : 0.8)
        link.attr('stroke-opacity', 0.75)
      })
      .on('click', (event, d) => {
        event.stopPropagation()
        onSelect(d)
      })

    // ── Tick ──────────────────────────────────────────────
    sim.on('tick', () => {
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y)
      node.attr('transform', d => `translate(${d.x},${d.y})`)
    })

    return () => sim.stop()
  }, [nodes, links]) // eslint-disable-line react-hooks/exhaustive-deps

  // Highlight selected node without re-running the simulation
  useEffect(() => {
    if (!svgRef.current) return
    d3.select(svgRef.current)
      .selectAll('.node circle')
      .attr('stroke', d => {
        if (selected?.id === d.id) return '#ffffff'
        return d.type === 'paper' ? '#fbbf24' : '#6c8aff'
      })
      .attr('stroke-width', d => selected?.id === d.id ? 2.5 : 1.5)
      .style('filter', d => selected?.id === d.id ? 'url(#glow)' : null)
  }, [selected])

  return <svg ref={svgRef} className="graph-svg" />
}
