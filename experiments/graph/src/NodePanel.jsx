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

            <div className="panel-stats">
              <div className="panel-stat">
                <span className="panel-stat-value">{node.degree}</span>
                <span className="panel-stat-label">Connections</span>
              </div>
              {node.isMain && (
                <div className="panel-stat">
                  <span className="panel-stat-value">Main</span>
                  <span className="panel-stat-label">Role</span>
                </div>
              )}
            </div>

            {onNavigate && node.external_id && (
              <button
                className="panel-link"
                style={{ border: 'none', cursor: 'pointer' }}
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
          </>
        ) : (
          <>
            <div className="panel-stats">
              <div className="panel-stat">
                <span className="panel-stat-value">{node.degree}</span>
                <span className="panel-stat-label">Connections</span>
              </div>
            </div>

            {node.body && (
              <div className="panel-section">
                <p className="panel-section-label">Body</p>
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
