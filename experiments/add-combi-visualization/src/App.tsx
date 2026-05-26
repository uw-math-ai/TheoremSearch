import { useEffect, useRef, useState } from "react";
import Graph from "./components/Graph";
import Legend from "./components/Legend";
import {
  fetchPaperByExternalId,
  fetchPaperGraph,
  fetchPaperInfo,
  fetchStatementDepsAndReps,
} from "./api";
import type {
  MinimalEdge,
  PaperGroup,
  PaperResponse,
  PaperSearchHit,
  Representation,
  StatementEdge,
  StatementNode,
} from "./types";
import "./App.css";

// Focal is hard-coded: this is a paper figure, not a search tool.
const FOCAL_EXTERNAL_ID = "add-combi";
const FOCAL_SOURCE       = "Lean Repo";

// All representation queries are restricted to this set of paper sources, so
// we surface only the focal → arXiv bridge (not formal-to-formal noise).
const REP_SOURCES = ["arXiv"];

// ---- Tunables ----
const REPRESENTATION_FANOUT          = 200;   // focal stmts queried for reps
const REPRESENTATION_THRESHOLD       = 0.85;
const REPRESENTATIONS_PER_STATEMENT  = 3;
// Each expanded outer paper is fetched in one /graph/paper?mode=minimal call
// (all its stmts + edges). Fewer-but-fuller papers compared to before.
const OUTER_PAPERS_TO_EXPAND         = 24;

// Lean-side "main" kinds — drops typeclass instances, auto-generated constructors,
// etc. The DB stores both long and short spellings ("theorem" / "thm").
const MAIN_FORMAL_KINDS = new Set([
  "theorem", "thm",
  "definition", "def",
  "structure", "struct",
  "inductive", "ind",
  "class",
]);

function isMainKind(source: string, kind: string | undefined): boolean {
  if (source !== "Lean Repo") return true;        // informal sources: keep all
  if (!kind) return true;                         // unknown: don't drop
  return MAIN_FORMAL_KINDS.has(kind);
}

function formalityOf(source: string): "formal" | "informal" {
  return source === "Lean Repo" ? "formal" : "informal";
}

// ---- Focal: kind filter, root detection, depth-3 BFS ----
function focalSubgraph(
  paper: PaperResponse,
  source: string,
): { keep: Set<string>; edges: MinimalEdge[] } {
  const allStmts = paper.statements;
  const main = new Set(
    allStmts.filter((s) => isMainKind(source, s.kind)).map((s) => s.statement_id),
  );
  // Edges between main stmts only.
  const mainEdges = paper.edges.filter(
    (e) => !e.cite_key && !e.cite_id && e.dep_id && main.has(e.src_id) && main.has(e.dep_id),
  );

  // Adjacency (src → deps) restricted to main stmts.
  const adj = new Map<string, string[]>();
  const indeg = new Map<string, number>();
  for (const sid of main) { adj.set(sid, []); indeg.set(sid, 0); }
  for (const e of mainEdges) {
    adj.get(e.src_id)!.push(e.dep_id!);
    indeg.set(e.dep_id!, (indeg.get(e.dep_id!) ?? 0) + 1);
  }
  // Keep every main-kind statement (no depth limit). The kind filter alone
  // is the focal trim; we want the full intra-paper dep web visible.
  const keep = new Set<string>(main);
  // Edges where both endpoints survived.
  const culledEdges = mainEdges.filter((e) => keep.has(e.src_id) && keep.has(e.dep_id!));
  return { keep, edges: culledEdges };
}

// ---- Outer paper expansion ----
//
// One /graph/paper call per outer paper gives us every statement in that
// paper plus the full within-paper edge set + cross-paper cites. We use FULL
// mode (not minimal) so edges carry their `methods` array — needed to filter
// notation-only deps for specific papers that come back too edge-dense.
//
// Per-paper denoise: paper titles matching DENOISE_TITLE_PATTERNS get any
// edge tagged `methods = ["llm"]` (notation-only) dropped, which thins out
// blobby papers where notation deps dominate.
const DENOISE_TITLE_PATTERNS = [
  /freiman/i,                          // "Freiman homorphisms on sparse..."
  /higher moments of convolutions/i,   // "Higher moments of convolutions"
];

function shouldDenoise(title: string | undefined): boolean {
  if (!title) return false;
  return DENOISE_TITLE_PATTERNS.some((re) => re.test(title));
}

function isNotationOnly(methods: string[] | undefined): boolean {
  return Array.isArray(methods) && methods.length === 1 && methods[0] === "llm";
}

async function expandOuterPaper(
  paperId: string,
  paperTitle: string | undefined,
): Promise<{
  stmts: Set<string>;
  intraEdges: StatementEdge[];
  citeTargets: Array<{ from: string; to_stmt: string; to_paper: string }>;
}> {
  const stmts = new Set<string>();
  const intraEdges: StatementEdge[] = [];
  const citeTargets: Array<{ from: string; to_stmt: string; to_paper: string }> = [];

  let res;
  try {
    res = await fetchPaperGraph(paperId, /* minimal */ false);
  } catch {
    return { stmts, intraEdges, citeTargets };
  }
  const denoise = shouldDenoise(paperTitle);
  for (const s of res.statements) stmts.add(s.statement_id);
  for (const e of res.edges) {
    if (!e.dep_id || e.dep_id === e.src_id) continue;
    if (e.cite_key || e.cite_id) {
      if (e.cite_id) citeTargets.push({ from: e.src_id, to_stmt: e.dep_id, to_paper: e.cite_id });
      continue;
    }
    if (denoise && isNotationOnly(e.methods)) continue;
    intraEdges.push({ source: e.src_id, target: e.dep_id, kind: "within_paper" });
  }
  return { stmts, intraEdges, citeTargets };
}

// ---- Final graph assembly ----
interface BuiltGraph {
  statements: StatementNode[];
  papers:     PaperGroup[];
  edges:      StatementEdge[];
}

function buildGraph(args: {
  focalPaperId: string;
  focalSource: string;
  focalTitle: string;
  focalStmtIds: Set<string>;
  focalEdges: MinimalEdge[];
  focalReps: Array<{ from: string; rep: Representation }>;
  outerPaperInfo: Map<string, { title: string; source: string }>;
  outerStmts: Map<string, { paper_id: string; source: string }>;
  outerIntraEdges: StatementEdge[];
  citeEdges: Array<{ src_id: string; dep_id: string }>;
}): BuiltGraph {
  // ---- All statements ----
  const stmts: StatementNode[] = [
    ...Array.from(args.focalStmtIds).map((sid) => ({
      id: sid, paper_id: args.focalPaperId, source: args.focalSource, kind: "focal" as const,
    })),
    ...Array.from(args.outerStmts.entries()).map(([sid, info]) => ({
      id: sid, paper_id: info.paper_id, source: info.source, kind: "outer" as const,
    })),
  ];
  const idSet = new Set(stmts.map((s) => s.id));

  // ---- Paper groups ----
  const byPaper = new Map<string, string[]>();
  for (const s of stmts) {
    const arr = byPaper.get(s.paper_id) ?? [];
    arr.push(s.id);
    byPaper.set(s.paper_id, arr);
  }
  const papers: PaperGroup[] = Array.from(byPaper.entries()).map(([pid, sids]) => {
    if (pid === args.focalPaperId) {
      return { id: pid, source: args.focalSource, title: args.focalTitle, statementIds: sids, kind: "focal" as const };
    }
    const info = args.outerPaperInfo.get(pid);
    const sourceFromStmts = stmts.find((s) => s.paper_id === pid)?.source ?? "other";
    return {
      id: pid,
      source: info?.source ?? sourceFromStmts,
      title: info?.title ?? "…",
      statementIds: sids,
      kind: "outer" as const,
    };
  });

  // ---- Edges ----
  // Self-loops dropped; (kind, src, dst) deduped.
  const seen = new Set<string>();
  const edges: StatementEdge[] = [];
  const push = (src: string, dst: string, kind: StatementEdge["kind"], similarity?: number) => {
    if (src === dst) return;
    if (!idSet.has(src) || !idSet.has(dst)) return;
    const key = kind + ":" + src + "->" + dst;
    if (seen.has(key)) return;
    seen.add(key);
    edges.push({ source: src, target: dst, kind, similarity });
  };
  for (const e of args.focalEdges) {
    if (!e.dep_id) continue;
    push(e.src_id, e.dep_id, "within_paper");
  }
  for (const e of args.outerIntraEdges) {
    push(e.source, e.target, "within_paper");
  }
  for (const e of args.citeEdges) {
    push(e.src_id, e.dep_id, "citation");
  }
  for (const r of args.focalReps) {
    push(r.from, r.rep.statement_id, "representation", r.rep.similarity);
  }

  // ---- Pruning ----
  // Treat all edges as undirected. Two-stage prune:
  //   (1) drop nodes not reachable from any focal stmt at all (isolated dots,
  //       and islands within outer papers whose within-paper deps don't link
  //       back to the bridge);
  //   (2) among the survivors, drop formal stmts that don't lie on any path
  //       to an informal stmt — i.e. formals with no informal representation,
  //       not even transitively.
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    if (!adj.has(e.source)) adj.set(e.source, []);
    if (!adj.has(e.target)) adj.set(e.target, []);
    adj.get(e.source)!.push(e.target);
    adj.get(e.target)!.push(e.source);
  }
  const bfsFrom = (seeds: Iterable<string>): Set<string> => {
    const out = new Set<string>();
    const q: string[] = [];
    for (const s of seeds) { if (idSet.has(s) && !out.has(s)) { out.add(s); q.push(s); } }
    let qh = 0;
    while (qh < q.length) {
      const sid = q[qh++];
      for (const n of adj.get(sid) ?? []) {
        if (out.has(n)) continue;
        out.add(n);
        q.push(n);
      }
    }
    return out;
  };

  // (1) reachable from focal.
  const focalReachable = bfsFrom(args.focalStmtIds);
  // (2) reachable from any informal stmt (within the focal-reachable set).
  const informalSeeds = stmts
    .filter((s) => s.source !== args.focalSource && focalReachable.has(s.id))
    .map((s) => s.id);
  const informalReachable = bfsFrom(informalSeeds);

  // Keep iff:
  //   - reachable from focal, AND
  //   - if it's formal (Lean Repo), also reachable from some informal stmt.
  const keep = (sid: string): boolean => {
    if (!focalReachable.has(sid)) return false;
    const s = stmts.find((x) => x.id === sid);
    if (!s) return false;
    if (s.source !== "Lean Repo") return true;          // informals stay
    return informalReachable.has(sid);                  // formals require informal anchor
  };

  const prunedStmts = stmts.filter((s) => keep(s.id));
  const prunedEdges = edges.filter((e) => keep(e.source) && keep(e.target));
  const survivingPaperIds = new Set(prunedStmts.map((s) => s.paper_id));
  const prunedPapers = papers
    .filter((p) => survivingPaperIds.has(p.id))
    .map((p) => ({
      ...p,
      statementIds: p.statementIds.filter((sid) => keep(sid)),
    }));

  return { statements: prunedStmts, papers: prunedPapers, edges: prunedEdges };
}

export default function App() {
  const [selected, setSelected] = useState<PaperSearchHit | null>(null);
  const [graph, setGraph] = useState<BuiltGraph | null>(null);
  const [status, setStatus] = useState<string>("");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [dims, setDims] = useState({ width: 1000, height: 720 });

  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        setDims({
          width: Math.max(400, Math.floor(e.contentRect.width)),
          height: Math.max(400, Math.floor(e.contentRect.height)),
        });
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // Auto-resolve the hard-coded focal paper on first mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setStatus(`Looking up ${FOCAL_EXTERNAL_ID}…`);
      try {
        const hit = await fetchPaperByExternalId(FOCAL_EXTERNAL_ID, FOCAL_SOURCE);
        if (cancelled) return;
        if (!hit) { setStatus(`Could not find paper "${FOCAL_EXTERNAL_ID}".`); return; }
        setSelected(hit);
      } catch (e) {
        if (!cancelled) setStatus(`Lookup failed: ${(e as Error).message}`);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;

    (async () => {
      setGraph(null);
      setStatus("Loading focal paper…");

      let paper: PaperResponse;
      try { paper = await fetchPaperGraph(selected.paper_id); }
      catch (e) {
        if (!cancelled) setStatus(`Failed to load paper: ${(e as Error).message}`);
        return;
      }
      if (cancelled) return;

      // ---- Focal subgraph (kind filter + depth-3 BFS from roots) ----
      const { keep: focalKeep, edges: focalEdges } = focalSubgraph(paper, selected.source);
      setStatus(`Focal subgraph: ${focalKeep.size} stmts (of ${paper.statements.length}), ${focalEdges.length} edges. Fetching focal reps…`);

      // ---- Focal representations ----
      const focalRepTargets = Array.from(focalKeep).slice(0, REPRESENTATION_FANOUT);
      const focalReps: Array<{ from: string; rep: Representation }> = [];
      await Promise.all(
        focalRepTargets.map(async (sid) => {
          try {
            const res = await fetchStatementDepsAndReps(
              sid, formalityOf(selected.source), REPRESENTATIONS_PER_STATEMENT, REP_SOURCES,
            );
            for (const r of res.representations ?? []) {
              if (r.similarity >= REPRESENTATION_THRESHOLD) focalReps.push({ from: sid, rep: r });
            }
          } catch { /* ignore */ }
        }),
      );
      if (cancelled) return;

      // ---- Entry points per outer paper (from reps + cite edges) ----
      const focalCites = paper.edges.filter(
        (e) => focalKeep.has(e.src_id) && e.cite_key && e.dep_id && e.cite_id,
      );
      const entriesByPaper = new Map<string, { source: string; entryStmts: Set<string> }>();
      const addEntry = (paper_id: string, source: string, stmt: string) => {
        if (paper_id === selected.paper_id) return;
        if (!entriesByPaper.has(paper_id))
          entriesByPaper.set(paper_id, { source, entryStmts: new Set() });
        entriesByPaper.get(paper_id)!.entryStmts.add(stmt);
      };
      for (const r of focalReps) addEntry(r.rep.paper_id, r.rep.source, r.rep.statement_id);
      for (const e of focalCites) addEntry(e.cite_id!, "other", e.dep_id!);

      setStatus(`Resolving ${entriesByPaper.size} outer paper titles…`);
      const outerPaperInfo = new Map<string, { title: string; source: string }>();
      await Promise.all(
        Array.from(entriesByPaper.keys()).map(async (pid) => {
          try {
            const info = await fetchPaperInfo(pid);
            outerPaperInfo.set(pid, { title: info.title, source: info.source });
            // Reconcile any "other"-tagged source from cite-only entries.
            if (entriesByPaper.get(pid)!.source === "other") {
              entriesByPaper.get(pid)!.source = info.source ?? "other";
            }
          } catch { /* ignore */ }
        }),
      );
      if (cancelled) return;

      // ---- Pick top-K outer papers to expand ----
      const ranked = Array.from(entriesByPaper.entries())
        .sort((a, b) => b[1].entryStmts.size - a[1].entryStmts.size);
      const toExpand = ranked.slice(0, OUTER_PAPERS_TO_EXPAND);
      const notExpanded = ranked.slice(OUTER_PAPERS_TO_EXPAND);

      setStatus(`Expanding ${toExpand.length} outer papers (all stmts each)…`);

      const outerStmts = new Map<string, { paper_id: string; source: string }>();
      const outerIntraEdges: StatementEdge[] = [];
      const citeEdgesAcc: Array<{ src_id: string; dep_id: string }> = [];

      // Initial entry-point stmts for non-expanded outer papers (kept as is).
      for (const [pid, info] of notExpanded) {
        for (const sid of info.entryStmts) {
          outerStmts.set(sid, { paper_id: pid, source: info.source });
        }
      }

      await Promise.all(
        toExpand.map(async ([pid, info]) => {
          const result = await expandOuterPaper(pid, outerPaperInfo.get(pid)?.title);
          if (cancelled) return;
          for (const sid of result.stmts) {
            outerStmts.set(sid, { paper_id: pid, source: info.source });
          }
          for (const e of result.intraEdges) outerIntraEdges.push(e);
          for (const c of result.citeTargets) {
            if (c.to_paper === selected.paper_id) {
              citeEdgesAcc.push({ src_id: c.from, dep_id: c.to_stmt });
              continue;
            }
            // Citation lands in an arXiv paper. Only render the edge if we
            // already have that paper in the graph; we don't expand new ones
            // here to keep the canvas bounded.
            citeEdgesAcc.push({ src_id: c.from, dep_id: c.to_stmt });
          }
        }),
      );
      if (cancelled) return;

      // Original focal citation edges.
      for (const e of focalCites) {
        citeEdgesAcc.push({ src_id: e.src_id, dep_id: e.dep_id! });
      }

      // Resolve any newly-introduced outer papers' titles (best-effort).
      const newPaperIds = new Set<string>();
      for (const v of outerStmts.values()) {
        if (!outerPaperInfo.has(v.paper_id) && v.paper_id !== selected.paper_id) {
          newPaperIds.add(v.paper_id);
        }
      }
      if (newPaperIds.size > 0) {
        await Promise.all(
          Array.from(newPaperIds).map(async (pid) => {
            try {
              const info = await fetchPaperInfo(pid);
              outerPaperInfo.set(pid, { title: info.title, source: info.source });
            } catch { /* ignore */ }
          }),
        );
        if (cancelled) return;
        // Update source on outerStmts entries we previously tagged "other".
        for (const [sid, info] of outerStmts) {
          const resolved = outerPaperInfo.get(info.paper_id);
          if (resolved?.source && info.source === "other") {
            outerStmts.set(sid, { paper_id: info.paper_id, source: resolved.source });
          }
        }
      }

      const g = buildGraph({
        focalPaperId: selected.paper_id,
        focalSource: selected.source,
        focalTitle: selected.title,
        focalStmtIds: focalKeep,
        focalEdges,
        focalReps,
        outerPaperInfo,
        outerStmts,
        outerIntraEdges,
        citeEdges: citeEdgesAcc,
      });
      setGraph(g);

      const nFocal  = g.statements.filter((s) => s.kind === "focal").length;
      const nOuter  = g.statements.filter((s) => s.kind === "outer").length;
      const nCite   = g.edges.filter((e) => e.kind === "citation").length;
      const nDep    = g.edges.filter((e) => e.kind === "within_paper").length;
      setStatus(
        `${nFocal} focal · ${nOuter} outer · ${g.papers.length - 1} other papers · ` +
          `${g.edges.filter((e) => e.kind === "representation").length} reps · ` +
          `${nCite} cites · ${nDep} within-paper deps`,
      );
    })();

    return () => { cancelled = true; };
  }, [selected]);

  return (
    <div className="app">
      <main className="app-main">
        <div className="graph-area" ref={containerRef}>
          {!graph ? (
            <div className="placeholder">{status || "Loading…"}</div>
          ) : (
            <Graph data={graph} width={dims.width} height={dims.height} />
          )}
          {graph && <Legend />}
        </div>
      </main>
      {status && (
        <footer className="app-footer">
          <span className="status">{status}</span>
        </footer>
      )}
    </div>
  );
}
