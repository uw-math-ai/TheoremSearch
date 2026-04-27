import { useEffect, useRef } from 'react'
import * as d3 from 'd3'

const STMT_BASE = 6
const PAPER_BASE = 14
const DEGREE_SCALE = 2.2
const STMT_MAX = 12

function nodeRadius(n) {
  if (n.type === 'paper') return PAPER_BASE
  return Math.min(STMT_BASE + n.degree * DEGREE_SCALE, STMT_MAX)
}

function linkStroke(l) {
  if (l.kind === 'membership') return '#475569'
  if (l.kind === 'inter')      return '#b45309'
  return '#4a6abf'
}
function linkWidth(l) {
  if (l.kind === 'membership') return 0.75
  if (l.kind === 'inter')      return 1.5
  return 1
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

    // ── BFS depth (run before forceLink mutates linkData) ─────
    // Build outgoing adjacency on raw string ids
    const adj = new Map(nodeData.map(n => [n.id, []]))
    for (const l of linkData) adj.get(l.source)?.push(l.target)

    const depthMap = new Map()
    const mainNode = nodeData.find(n => n.isMain)
    if (mainNode) {
      depthMap.set(mainNode.id, 0)
      const q = [mainNode.id]
      while (q.length) {
        const id = q.shift()
        const d = depthMap.get(id)
        for (const nb of adj.get(id) || []) {
          if (!depthMap.has(nb)) { depthMap.set(nb, d + 1); q.push(nb) }
        }
      }
    }
    const maxDepth = depthMap.size ? Math.max(...depthMap.values()) : 0

    // Pin main node near top-centre; scale layer height to viewport
    const MAIN_Y = Math.max(60, height * 0.1)
    // Ghost nodes sit in a compact half-row just below the main paper;
    // dep nodes get full LAYER_H spacing so the tree can breathe
    const LAYER_H = maxDepth > 0
      ? Math.min(160, (height * 0.85) / maxDepth)
      : 140
    const GHOST_Y = MAIN_Y + LAYER_H * 0.45   // compact ghost row
    if (mainNode) { mainNode.fx = width / 2; mainNode.fy = MAIN_Y }

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
            if (d.kind === 'membership') return 50
            const either = d.source.type === 'paper' || d.target.type === 'paper'
            return either ? 140 : 100
          })
          // Very weak — forceY + barycenter own the layout; links just keep edges visible
          .strength(d => d.kind === 'membership' ? 0.08 : 0.05)
      )
      .force('charge', d3.forceManyBody().strength(d => d.type === 'paper' ? -1200 : -700))
      // Strict row assignment — nodes are pinned hard to their depth layer
      .force('y', d3.forceY(d => {
        if (d.ghost) return GHOST_Y
        return MAIN_Y + (depthMap.get(d.id) ?? maxDepth) * LAYER_H
      }).strength(d => d.ghost ? 0.97 : 0.9))
      .force('collide', d3.forceCollide().radius(d => nodeRadius(d) + 30).strength(1.0))
      // Barycenter force: pull each node toward the mean x of its dep-edge neighbours.
      // Runs every tick — this is the continuous Sugiyama crossing-minimisation
      // heuristic. Weighted 2:1 toward parent positions (nodes at shallower depth)
      // since aligning children under parents is most effective for tree untangling.
      .force('barycenter', alpha => {
        const nbx = new Map(nodeData.map(n => [n.id, { sum: 0, count: 0, wsum: 0, wcount: 0 }]))
        for (const l of linkData) {
          if (l.kind === 'membership') continue
          const s = l.source, t = l.target
          if (s.x == null || t.x == null) continue
          const sd = depthMap.get(s.id) ?? 0
          const td = depthMap.get(t.id) ?? 0
          // parent→child: target is deeper, so target gets weight-2 pull from source
          // child→parent: source is deeper, so source gets weight-2 pull from target
          const sWeight = sd > td ? 2 : 1
          const tWeight = td > sd ? 2 : 1
          nbx.get(s.id).wsum += t.x * sWeight; nbx.get(s.id).wcount += sWeight
          nbx.get(t.id).wsum += s.x * tWeight; nbx.get(t.id).wcount += tWeight
        }
        for (const n of nodeData) {
          if (n.fx != null) continue
          const nb = nbx.get(n.id)
          if (!nb || nb.wcount === 0) continue
          n.vx += (nb.wsum / nb.wcount - n.x) * 0.7 * alpha
        }
      })

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
      .attr('stroke-opacity', 0.5)

    const depLink = g.append('g')
      .attr('class', 'dep-links')
      .selectAll('path')
      .data(linkData.filter(l => l.kind !== 'membership'))
      .join('path')
      .attr('fill', 'none')
      .attr('stroke', l => linkStroke(l))
      .attr('stroke-width', l => linkWidth(l))
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
        const maxLen = d.type === 'paper' ? 40 : 26
        return raw.length > maxLen ? raw.slice(0, maxLen - 1) + '…' : raw
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
        memberLink.attr('stroke-opacity', 0.5)
      })
      .on('click', (event, d) => {
        event.stopPropagation()
        onSelect(d)
      })
      .on('dblclick', (e, d) => {
        e.stopPropagation()
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
