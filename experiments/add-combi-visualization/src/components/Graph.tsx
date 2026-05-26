import { useEffect, useMemo, useRef } from "react";
import * as d3 from "d3";
import type { PaperGroup, StatementEdge, StatementNode } from "../types";
import {
  EDGE_COLORS,
  FOCAL_OUTLINE,
  SOURCE_COLORS,
  STATEMENT_COLORS,
} from "../colors";

interface Props {
  data: {
    statements: StatementNode[];
    papers:     PaperGroup[];
    edges:      StatementEdge[];
  };
  width: number;
  height: number;
}

interface SimNode extends d3.SimulationNodeDatum, StatementNode {}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  kind: StatementEdge["kind"];
  similarity?: number;
}

// ---- Layout constants ----
const TOP_MARGIN   = 40;
const SIDE_MARGIN  = 40;
const BRIDGE_GAP   = 80;

// "Formal" side = Lean Repo papers (left half); everything else is informal (right).
function isFormalSource(source: string): boolean {
  return source === "Lean Repo";
}

// ---- Hull geometry ----

function paddedHull(points: [number, number][], padding: number): [number, number][] | null {
  if (points.length < 1) return null;
  if (points.length === 1) {
    const [x, y] = points[0];
    return Array.from({ length: 18 }, (_, i) => {
      const t = (i / 18) * Math.PI * 2;
      return [x + padding * Math.cos(t), y + padding * Math.sin(t)] as [number, number];
    });
  }
  if (points.length === 2) {
    const [a, b] = points;
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const len = Math.hypot(dx, dy) || 1;
    const ux = -dy / len, uy = dx / len;
    const half = len / 2 + padding;
    return [
      [mx - (dx / len) * half + ux * padding, my - (dy / len) * half + uy * padding],
      [mx + (dx / len) * half + ux * padding, my + (dy / len) * half + uy * padding],
      [mx + (dx / len) * half - ux * padding, my + (dy / len) * half - uy * padding],
      [mx - (dx / len) * half - ux * padding, my - (dy / len) * half - uy * padding],
    ];
  }
  const hull = d3.polygonHull(points);
  if (!hull) return null;
  const [cx, cy] = d3.polygonCentroid(hull);
  return hull.map(([x, y]) => {
    const dx = x - cx, dy = y - cy;
    const len = Math.hypot(dx, dy) || 1;
    return [x + (dx / len) * padding, y + (dy / len) * padding] as [number, number];
  });
}

const hullPath = d3.line<[number, number]>()
  .x((d) => d[0]).y((d) => d[1])
  .curve(d3.curveCatmullRomClosed.alpha(0.7));

// ---- Custom pin forces (pull each node toward its tree-position target) ----

function forcePinX(targetX: Map<string, number>, strength: number) {
  let nodes: SimNode[] = [];
  function force(alpha: number) {
    for (const n of nodes) {
      const tx = targetX.get(n.id);
      if (tx === undefined) continue;
      n.vx = (n.vx ?? 0) + (tx - (n.x ?? 0)) * strength * alpha;
    }
  }
  force.initialize = (n: SimNode[]) => { nodes = n; };
  return force;
}

function forcePinY(targetY: Map<string, number>, strength: number) {
  let nodes: SimNode[] = [];
  function force(alpha: number) {
    for (const n of nodes) {
      const ty = targetY.get(n.id);
      if (ty === undefined) continue;
      n.vy = (n.vy ?? 0) + (ty - (n.y ?? 0)) * strength * alpha;
    }
  }
  force.initialize = (n: SimNode[]) => { nodes = n; };
  return force;
}

export default function Graph({ data, width, height }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);

  const { simNodes, simLinks, paperById, degree, sideTargetX, yCenter, stmtsByPaper, focalPaperId } = useMemo(() => {
    const sn: SimNode[] = data.statements.map((s) => ({ ...s }));
    const byId = new Map(sn.map((n) => [n.id, n]));
    const sl: SimLink[] = data.edges
      .filter((e) => byId.has(e.source) && byId.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, kind: e.kind, similarity: e.similarity }));

    const focal = data.papers.find((p) => p.kind === "focal")!;

    // ---- Weighted degree per node (rep edges count 3×) ----
    const degree = new Map<string, number>();
    const bump = (id: string, w: number) => degree.set(id, (degree.get(id) ?? 0) + w);
    for (const e of data.edges) {
      const w = e.kind === "representation" ? 3 : 1;
      bump(e.source, w);
      bump(e.target, w);
    }

    // ---- Side anchors ----
    const midX        = width / 2;
    const sideW       = Math.max(200, midX - SIDE_MARGIN - BRIDGE_GAP / 2);
    const leftCenter  = SIDE_MARGIN + sideW / 2;
    const rightCenter = midX + BRIDGE_GAP / 2 + sideW / 2;
    const yCenter     = height / 2;

    // Per-statement x-anchor: the *side*, not a specific cell. Force layout
    // does the rest. Each informal paper gets a small random x offset within
    // its side so the initial sim positions cluster them, not pile up.
    const sideTargetX = new Map<string, number>();
    const stmtsByPaper = new Map<string, SimNode[]>();
    for (const n of sn) {
      const formal = isFormalSource(n.source);
      sideTargetX.set(n.id, formal ? leftCenter : rightCenter);
      const arr = stmtsByPaper.get(n.paper_id) ?? [];
      arr.push(n);
      stmtsByPaper.set(n.paper_id, arr);
    }

    // ---- Initial positions: one random offset per paper, then jitter ----
    // Deterministic per-paper offset (seeded from paper_id) so the figure
    // doesn't re-randomise on every focal-paper reload.
    const hash = (s: string) => {
      let h = 2166136261 >>> 0;
      for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = (h * 16777619) >>> 0; }
      return h / 4294967295; // [0, 1)
    };
    const paperInit = new Map<string, { x: number; y: number }>();
    const sideH = Math.max(200, height - SIDE_MARGIN * 2);
    for (const p of data.papers) {
      const formal = isFormalSource(p.source);
      if (p.id === focal.id) {
        paperInit.set(p.id, { x: leftCenter, y: yCenter });
        continue;
      }
      const r1 = hash(p.id);
      const r2 = hash(p.id + "_y");
      paperInit.set(p.id, {
        x: (formal ? leftCenter : rightCenter) + (r1 - 0.5) * sideW * 0.85,
        y: yCenter + (r2 - 0.5) * sideH * 0.85,
      });
    }
    for (const n of sn) {
      const init = paperInit.get(n.paper_id);
      if (!init) continue;
      n.x = init.x + (Math.random() - 0.5) * 16;
      n.y = init.y + (Math.random() - 0.5) * 16;
    }

    const paperById = new Map(data.papers.map((p) => [p.id, p]));

    return {
      simNodes: sn, simLinks: sl, paperById,
      degree, sideTargetX, yCenter, stmtsByPaper,
      focalPaperId: focal.id,
    };
  }, [data, width, height]);

  useEffect(() => {
    if (!svgRef.current) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    svg.append("rect")
      .attr("width", width)
      .attr("height", height)
      .attr("fill", "white");

    const container = svg.append("g");
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 6])
      .on("zoom", (event) => container.attr("transform", event.transform));
    svg.call(zoom);

    const gHulls = container.append("g").attr("class", "hulls");
    const gEdges = container.append("g").attr("class", "edges");
    const gReps  = container.append("g").attr("class", "rep-edges");
    const gNodes = container.append("g").attr("class", "nodes");
    const gLabels = container.append("g").attr("class", "labels");

    // ---- Non-rep edges (within-paper + citation) ----
    const nonRepLinks = simLinks.filter((l) => l.kind !== "representation");
    const linkSel = gEdges.selectAll<SVGLineElement, SimLink>("line")
      .data(nonRepLinks)
      .join("line")
      .attr("stroke", (d) => EDGE_COLORS[d.kind])
      .attr("stroke-opacity", (d) => (d.kind === "within_paper" ? 0.50 : 0.85))
      .attr("stroke-width", (d) => (d.kind === "within_paper" ? 0.7 : 1.2))
      .attr("stroke-linecap", "round");

    // ---- Representation edges (red bridge) ----
    const repLinks = simLinks.filter((l) => l.kind === "representation");
    const repSel = gReps.selectAll<SVGLineElement, SimLink>("line")
      .data(repLinks)
      .join("line")
      .attr("stroke", EDGE_COLORS.representation)
      .attr("stroke-opacity", (d) => {
        const s = d.similarity ?? 0.9;
        return Math.min(1, 0.55 + 0.45 * Math.max(0, s - 0.9) / 0.1);
      })
      .attr("stroke-width", 1.4)
      .attr("stroke-linecap", "round");

    // ---- Statement dots ----
    // Node radius scales with weighted degree (rep edges count 3×), capped.
    const dotRadius = (n: SimNode) => {
      const d = degree.get(n.id) ?? 0;
      const base = n.kind === "focal" ? 2.4 : 2.2;
      return Math.min(8.5, base + Math.sqrt(d) * 0.65);
    };

    const nodeSel = gNodes.selectAll<SVGCircleElement, SimNode>("circle")
      .data(simNodes, (d) => d.id)
      .join("circle")
      .attr("r", dotRadius)
      .attr("fill", (d) => STATEMENT_COLORS[d.source ?? "other"] ?? STATEMENT_COLORS.other)
      .attr("stroke", "white")
      .attr("stroke-width", 0.8)
      .call(
        d3.drag<SVGCircleElement, SimNode>()
          .on("start", (event, d) => {
            if (!event.active) sim.alphaTarget(0.2).restart();
            d.fx = d.x; d.fy = d.y;
          })
          .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
          .on("end", (event, d) => {
            if (!event.active) sim.alphaTarget(0);
            d.fx = null; d.fy = null;
          }),
      );
    nodeSel.append("title").text((d) => `${d.id.slice(0, 8)} · ${d.source}`);

    // ---- Paper labels ----
    const labelSel = gLabels.selectAll<SVGTextElement, PaperGroup>("text")
      .data(Array.from(paperById.values()))
      .join("text")
      .attr("text-anchor", "middle")
      .attr("font-family", "system-ui, -apple-system, sans-serif")
      .attr("font-size", (d) => (d.id === focalPaperId ? 28 : 15))
      .attr("font-weight", (d) => (d.id === focalPaperId ? 700 : 600))
      .attr("fill", (d) => (d.id === focalPaperId ? FOCAL_OUTLINE : "#334155"))
      .attr("paint-order", "stroke")
      .attr("stroke", "white")
      .attr("stroke-width", 5)
      .text((d) => {
        const cap = d.id === focalPaperId ? 64 : 38;
        return d.title.length > cap ? d.title.slice(0, cap - 1) + "…" : d.title;
      });

    // ---- Forces (force-directed, side-anchored) ----
    const sim = d3.forceSimulation<SimNode>(simNodes)
      // Real force layout: link force pulls connected stmts together, charge
      // repels, collide keeps spacing, and per-stmt pinX/pinY (medium-strength)
      // keep each paper's stmts near their grid-cell centre.
      .force(
        "link",
        d3.forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance((d) => {
            if (d.kind === "within_paper") return 18;
            if (d.kind === "citation")     return 60;
            return 220; // representation: long bridge edges
          })
          .strength((d) => {
            if (d.kind === "within_paper")   return 0.40;
            if (d.kind === "citation")       return 0.12;
            return 0.015; // representation: very weak — don't yank sides together
          }),
      )
      .force("charge", d3.forceManyBody<SimNode>().strength(-14))
      .force("collide", d3.forceCollide<SimNode>().radius((n) => dotRadius(n) + 1.3).strength(0.8))
      .force("sideX", forcePinX(sideTargetX, 0.04))
      .force("centerY", d3.forceY<SimNode>(yCenter).strength(0.06))
      .on("tick", ticked)
      .on("end", () => { drawHulls(); placeLabels(); });

    const HEAVY_EVERY = 8;
    let tickCount = 0;

    function ticked() {
      linkSel
        .attr("x1", (d) => (d.source as SimNode).x ?? 0)
        .attr("y1", (d) => (d.source as SimNode).y ?? 0)
        .attr("x2", (d) => (d.target as SimNode).x ?? 0)
        .attr("y2", (d) => (d.target as SimNode).y ?? 0);
      repSel
        .attr("x1", (d) => (d.source as SimNode).x ?? 0)
        .attr("y1", (d) => (d.source as SimNode).y ?? 0)
        .attr("x2", (d) => (d.target as SimNode).x ?? 0)
        .attr("y2", (d) => (d.target as SimNode).y ?? 0);
      nodeSel.attr("cx", (d) => d.x ?? 0).attr("cy", (d) => d.y ?? 0);
      if ((tickCount++ % HEAVY_EVERY) === 0) {
        drawHulls();
        placeLabels();
      }
    }

    function drawHulls() {
      const list: { paper: PaperGroup; path: string }[] = [];
      for (const paper of paperById.values()) {
        const own = stmtsByPaper.get(paper.id);
        if (!own || own.length === 0) continue;
        const pts: [number, number][] = new Array(own.length);
        for (let i = 0; i < own.length; i++) pts[i] = [own[i].x ?? 0, own[i].y ?? 0];
        const hull = paddedHull(pts, paper.id === focalPaperId ? 22 : 16);
        if (!hull) continue;
        const path = hullPath(hull);
        if (path) list.push({ paper, path });
      }
      gHulls.selectAll<SVGPathElement, { paper: PaperGroup; path: string }>("path")
        .data(list, (d) => d.paper.id)
        .join("path")
        .attr("d", (d) => d.path)
        .attr("fill", (d) => SOURCE_COLORS[d.paper.source] ?? SOURCE_COLORS.other)
        .attr("fill-opacity", (d) => (d.paper.id === focalPaperId ? 0.13 : 0.10))
        .attr("stroke", (d) => SOURCE_COLORS[d.paper.source] ?? SOURCE_COLORS.other)
        .attr("stroke-opacity", (d) => (d.paper.id === focalPaperId ? 0.65 : 0.40))
        .attr("stroke-width", (d) => (d.paper.id === focalPaperId ? 2.0 : 1.1));
    }

    function placeLabels() {
      // Each label tracks its paper's live centroid: x = mean of stmt x,
      // y = (topmost stmt y) minus a small padding so it sits just above the
      // blob's top.
      labelSel
        .attr("x", (d) => {
          const own = stmtsByPaper.get(d.id);
          if (!own || own.length === 0) return 0;
          let sx = 0;
          for (const n of own) sx += n.x ?? 0;
          return sx / own.length;
        })
        .attr("y", (d) => {
          const own = stmtsByPaper.get(d.id);
          if (!own || own.length === 0) return 0;
          let mn = Infinity;
          for (const n of own) { const y = n.y ?? 0; if (y < mn) mn = y; }
          // Use the largest visible radius in the blob as the extra offset,
          // so labels never collide with the topmost dot.
          let maxR = 0;
          for (const n of own) { const r = dotRadius(n); if (r > maxR) maxR = r; }
          return mn - maxR - (d.id === focalPaperId ? 16 : 8);
        });
    }

    return () => { sim.stop(); };
  }, [simNodes, simLinks, paperById, degree, sideTargetX, yCenter, stmtsByPaper, focalPaperId, width, height]);

  return <svg ref={svgRef} width={width} height={height} />;
}
