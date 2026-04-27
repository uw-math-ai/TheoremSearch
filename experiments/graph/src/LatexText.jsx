import katex from 'katex'
import 'katex/dist/katex.min.css'

// Split text into alternating plain/math segments.
// Handles $$...$$ (display) and $...$ (inline).
function tokenize(text) {
  const tokens = []
  const re = /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)/g
  let last = 0
  let m
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) tokens.push({ type: 'text', value: text.slice(last, m.index) })
    const raw = m[0]
    const display = raw.startsWith('$$')
    const inner = display ? raw.slice(2, -2) : raw.slice(1, -1)
    tokens.push({ type: 'math', display, value: inner })
    last = m.index + raw.length
  }
  if (last < text.length) tokens.push({ type: 'text', value: text.slice(last) })
  return tokens
}

function renderMath(value, display) {
  try {
    return katex.renderToString(value, { displayMode: display, throwOnError: false })
  } catch {
    return value
  }
}

export default function LatexText({ children, className }) {
  if (!children) return null
  const tokens = tokenize(children)
  return (
    <span className={className}>
      {tokens.map((tok, i) =>
        tok.type === 'text'
          ? <span key={i}>{tok.value}</span>
          : <span
              key={i}
              style={tok.display ? { display: 'block', overflowX: 'auto' } : undefined}
              dangerouslySetInnerHTML={{ __html: renderMath(tok.value, tok.display) }}
            />
      )}
    </span>
  )
}
