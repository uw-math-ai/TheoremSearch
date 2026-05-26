import { useEffect, useRef, useState } from "react";
import { searchPapers } from "../api";
import type { PaperSearchHit } from "../types";

interface Props {
  onSelect: (paper: PaperSearchHit) => void;
}

export default function PaperSearch({ onSelect }: Props) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<PaperSearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const reqId = useRef(0);

  useEffect(() => {
    const term = q.trim();
    if (!term) {
      setHits([]);
      return;
    }
    const myId = ++reqId.current;
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const papers = await searchPapers(term, 8);
        if (reqId.current === myId) setHits(papers);
      } catch {
        if (reqId.current === myId) setHits([]);
      } finally {
        if (reqId.current === myId) setLoading(false);
      }
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <div className="search">
      <input
        className="search-input"
        placeholder="Search papers by title, arXiv ID, or repo slug…"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && q.trim() && (
        <ul className="search-results">
          {loading && <li className="search-status">Searching…</li>}
          {!loading && hits.length === 0 && <li className="search-status">No matches.</li>}
          {hits.map((p) => (
            <li
              key={p.paper_id}
              className="search-hit"
              onMouseDown={(e) => {
                e.preventDefault();
                onSelect(p);
                setOpen(false);
                setQ(p.title);
              }}
            >
              <div className="search-hit-title">{p.title}</div>
              <div className="search-hit-meta">
                <span className="badge">{p.source}</span>
                <span className="ext-id">{p.external_id}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
