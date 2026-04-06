import LatexText from './LatexText'

export default function NodePanel({ node, onClose, onNavigate }) {
  const isPaper = node.type === 'paper'
  const arxivUrl = node.external_id
    ? `https://arxiv.org/abs/${node.external_id}`
    : null

  return (
    <aside className="node-panel">
      <div className="panel-header">
        <span className={`panel-type-badge ${isPaper ? 'paper' : 'statement'}`}>
          {isPaper ? 'Paper' : 'Statement'}
        </span>
        {!isPaper && node.name && (
          <span className="panel-name">{node.name}</span>
        )}
        <button className="panel-close" onClick={onClose} aria-label="Close">✕</button>
      </div>

      <div className="panel-body">
        {isPaper ? (
          <>
            <h3 className="panel-title"><LatexText>{node.name}</LatexText></h3>

            <div className="panel-meta">
              <div className="panel-meta-chip">
                <span className="panel-meta-value">{node.degree}</span>
                <span className="panel-meta-label">Connections</span>
              </div>
              {node.isMain && (
                <div className="panel-meta-chip">
                  <span className="panel-meta-value">Main</span>
                  <span className="panel-meta-label">Role</span>
                </div>
              )}
            </div>

            <div className="panel-actions">
              {onNavigate && node.external_id && (
                <button
                  className="panel-link"
                  onClick={() => { onNavigate(node.external_id); onClose() }}
                >
                  → View Dependency Graph
                </button>
              )}
              {arxivUrl && (
                <a
                  className="panel-link"
                  href={arxivUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  ↗ View on arXiv
                </a>
              )}
            </div>
          </>
        ) : (
          <>
            <div className="panel-meta">
              <div className="panel-meta-chip">
                <span className="panel-meta-value">{node.degree}</span>
                <span className="panel-meta-label">Connections</span>
              </div>
            </div>

            {node.body && (
              <div className="panel-section">
                <p className="panel-section-label">Statement</p>
                <p className="panel-text"><LatexText>{node.body}</LatexText></p>
              </div>
            )}

            {node.note && (
              <div className="panel-section">
                <p className="panel-section-label">Note</p>
                <p className="panel-text"><LatexText>{node.note}</LatexText></p>
              </div>
            )}

            {node.proof && (
              <div className="panel-section">
                <p className="panel-section-label">Proof</p>
                <p className="panel-text proof"><LatexText>{node.proof}</LatexText></p>
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  )
}
