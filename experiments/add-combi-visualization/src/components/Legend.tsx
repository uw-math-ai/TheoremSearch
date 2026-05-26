import { EDGE_COLORS, SOURCE_COLORS } from "../colors";

// Explicit display rows — labels and colours are decoupled from the raw
// paper.source / EdgeKind keys so we can use figure-friendly names.
const PAPER_ENTRIES: { label: string; color: string }[] = [
  { label: "add-combi (Lean Repo)", color: SOURCE_COLORS["Lean Repo"] },
  { label: "arXiv paper",           color: SOURCE_COLORS["arXiv"] },
];

const EDGE_ENTRIES: { label: string; color: string }[] = [
  { label: "Dependency",     color: EDGE_COLORS.within_paper },
  { label: "Representation", color: EDGE_COLORS.representation },
];

export default function Legend() {
  return (
    <div className="legend">
      <div className="legend-section">
        <div className="legend-title">Papers</div>
        {PAPER_ENTRIES.map((e) => (
          <div className="legend-row" key={e.label}>
            <span
              className="legend-swatch"
              style={{
                background: e.color,
                opacity: 0.3,
                borderColor: e.color,
              }}
            />
            <span>{e.label}</span>
          </div>
        ))}
      </div>

      <div className="legend-section">
        <div className="legend-title">Edges</div>
        {EDGE_ENTRIES.map((e) => (
          <div className="legend-row" key={e.label}>
            <span className="legend-line" style={{ background: e.color }} />
            <span>{e.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
