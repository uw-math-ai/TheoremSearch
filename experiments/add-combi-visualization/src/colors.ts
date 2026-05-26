// Visual vocabulary aligned with the paper:
//   Papers (convex hulls) coloured by source.
//   Representation clusters (halos crossing hull boundaries) — drawn neutrally; the
//   topological grouping itself is the statement that these statements 'say the same thing'.
//   Edges between statements are either Citations or Within-paper dependencies.

import type { EdgeKind } from "./types";

export const EDGE_COLORS: Record<EdgeKind, string> = {
  citation:       "#f59e0b",  // amber
  within_paper:   "#94a3b8",  // slate (de-emphasised; within-paper deps are scaffolding)
  representation: "#dc2626",  // red — cross-paper semantic neighbour (focal → arXiv)
};

export const EDGE_LABELS: Record<EdgeKind, string> = {
  citation:       "Citation",
  within_paper:   "Within-paper dependency",
  representation: "Representation (→ arXiv)",
};

// Paper hull colours, by paper.source. "other" used as fallback.
export const SOURCE_COLORS: Record<string, string> = {
  "arXiv":          "#5b8def",
  "Lean Community": "#10b981",
  "Lean Repo":      "#8b5cf6",
  other:            "#94a3b8",
};

// Statement dot colours, by source. Slightly darker than the hull tint.
export const STATEMENT_COLORS: Record<string, string> = {
  "arXiv":          "#2563eb",
  "Lean Community": "#059669",
  "Lean Repo":      "#7c3aed",
  other:            "#64748b",
};

export const FOCAL_OUTLINE = "#0b1f5c";
