// API response types — mirror /graph/paper and /graph/statement in mode=minimal.

export interface PaperSearchHit {
  paper_id: string;
  title: string;
  external_id: string;
  source: string;
}

export interface MinimalPaper {
  paper_id: string;
  title: string;
}

export interface MinimalStatement {
  statement_id: string;
  // Populated when /graph/paper is called in mode=full. Mostly absent on
  // /graph/statement walks (the StatementNode model doesn't carry kind).
  kind?: string;
}

// Edge from /graph/paper?mode=minimal.
// - cite_key === null && cite_id === null  → intra-paper dependency
// - cite_key !== null                       → external citation (resolved or not)
export interface MinimalEdge {
  src_id: string;
  dep_id: string | null;
  cite_id: string | null;
  cite_key: string | null;
  // Populated only when /graph/paper is called in full mode (default).
  methods?: string[];
}

export interface PaperResponse {
  paper: MinimalPaper;
  statements: MinimalStatement[];
  edges: MinimalEdge[];
}

export interface Representation {
  statement_id: string;
  paper_id: string;
  source: string;
  similarity: number;
}

export interface StatementResponse {
  root: { statement_id: string; name?: string };
  nodes: MinimalStatement[];
  edges: MinimalEdge[];
  representations?: Representation[];
}

export interface PaperInfo {
  paper_id: string;
  title: string;
  source: string;
}

// --- Universal-graph viz model (hub-and-spoke: papers + statements) ---

export type EdgeKind = "citation" | "within_paper" | "representation";

export interface StatementNode {
  id: string;             // statement_id
  paper_id: string;
  source: string;
  kind: "focal" | "outer";
}

export interface PaperGroup {
  id: string;             // paper_id
  source: string;
  title: string;
  statementIds: string[]; // statements of this paper appearing in the viz
  kind: "focal" | "outer";
}

export interface StatementEdge {
  source: string;
  target: string;
  kind: EdgeKind;
  similarity?: number;    // present on representation edges
}
