import type {
  PaperInfo,
  PaperResponse,
  PaperSearchHit,
  StatementResponse,
} from "./types";

const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  "https://api.theoremsearch.com";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new Error(`${path} → ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function searchPapers(q: string, limit = 8): Promise<PaperSearchHit[]> {
  const params = new URLSearchParams({ q, limit: String(limit) });
  const { papers } = await getJSON<{ papers: PaperSearchHit[] }>(
    `/paper-search?${params}`,
  );
  return papers;
}

// Full mode (default) returns statement.kind, body, etc. — needed for the
// focal paper. Minimal mode returns just the structure (statement_id + edge
// endpoints) and is what we want for outer papers, where we just need the
// dep graph.
export async function fetchPaperGraph(
  paperId: string,
  minimal = false,
): Promise<PaperResponse> {
  const suffix = minimal ? "?mode=minimal" : "";
  return getJSON<PaperResponse>(`/graph/paper/${paperId}${suffix}`);
}

// Look up a paper by its external_id (e.g. arXiv ID or repo slug). Filter by
// source when needed to disambiguate (e.g. "add-combi" exists as both a Lean
// Community blueprint and a Lean Repo).
export async function fetchPaperByExternalId(
  externalId: string,
  source?: string,
): Promise<PaperSearchHit | null> {
  const params = new URLSearchParams({ q: externalId, limit: "20" });
  const { papers } = await getJSON<{ papers: PaperSearchHit[] }>(
    `/paper-search?${params}`,
  );
  const exact = papers.find(
    (p) => p.external_id === externalId && (!source || p.source === source),
  );
  return exact ?? null;
}

export async function fetchRepresentations(
  statementId: string,
  n = 10,
  sources?: string[],
): Promise<StatementResponse> {
  const params = new URLSearchParams({
    mode: "minimal",
    return: "representations",
    n_representations: String(n),
  });
  for (const s of sources ?? []) params.append("representation_sources", s);
  return getJSON<StatementResponse>(
    `/graph/statement/${statementId}?${params}`,
  );
}

// Outer-paper labelling: pulls just `paper` from the full-mode response.
// Tiny payload per call; we run these in parallel for distinct outer paper_ids.
export async function fetchPaperInfo(paperId: string): Promise<PaperInfo> {
  const { paper } = await getJSON<{ paper: PaperInfo }>(
    `/graph/paper/${paperId}?return=paper`,
  );
  return paper;
}

// One-hop outgoing deps for a single statement. nodes + edges only.
export async function fetchStatementDeps(
  statementId: string,
  formality: "informal" | "formal",
): Promise<StatementResponse> {
  const params = new URLSearchParams({
    direction: "src",
    formality,
    mode: "minimal",
  });
  params.append("return", "nodes");
  params.append("return", "edges");
  return getJSON<StatementResponse>(
    `/graph/statement/${statementId}?${params}`,
  );
}

// One-hop deps + top-k representations for a single statement, in one call.
export async function fetchStatementDepsAndReps(
  statementId: string,
  formality: "informal" | "formal",
  nRepresentations: number,
  sources?: string[],
): Promise<StatementResponse> {
  const params = new URLSearchParams({
    direction: "src",
    formality,
    mode: "minimal",
    n_representations: String(nRepresentations),
  });
  params.append("return", "nodes");
  params.append("return", "edges");
  params.append("return", "representations");
  for (const s of sources ?? []) params.append("representation_sources", s);
  return getJSON<StatementResponse>(
    `/graph/statement/${statementId}?${params}`,
  );
}
