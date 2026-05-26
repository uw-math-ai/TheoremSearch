# Universal Graph viz

One-page D3 + React tool for screenshotting the universal graph around a paper.

## Run

```bash
npm install
npm run dev      # http://localhost:5173
```

Default API base is `https://api.theoremsearch.com`. Override with a `.env`:

```
VITE_API_BASE=http://localhost:8000
```

`http://localhost:5173` is on the API's CORS allow-list.

## What it shows

- Search a paper by title or external ID (arXiv ID, repo slug…).
- The chosen paper's statements form a dense inner cluster (focal, dark blue).
- Edges radiate outward to other statements / papers:
  - **Within paper** — blue
  - **Citation → statement** — amber
  - **Citation → paper** (resolved only to the cited paper) — pale amber
  - **Representation** (cross-paper semantic neighbour) — magenta
- Drag nodes to reposition; scroll to zoom; right-click → save as PNG for screenshots.

## Tunables

In `src/App.tsx`:

- `REPRESENTATION_FANOUT` — max # of focal statements we fetch representations for (default 80).
- `REPRESENTATIONS_PER_STATEMENT` — top-k representations per statement (default 6).

Both are capped to keep first paint responsive on large Lean repos. Raise for richer pictures.
