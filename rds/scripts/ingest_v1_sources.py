"""Copy the non-arXiv v1 sources into v2 (paper / statement / informal_metadata).

The Stacks Project, ProofWiki and four open textbooks were only ever ingested
into v1 (`postgres` database, theorem_search_qwen8b). This copies their
statements into the v2 schema; slogans and embeddings are then generated with
the v2 pipelines, exactly as for arXiv:

    python -m pipeline.generate_slogans --chain -m qwen3-235b -w 8 \\
        -c "paper.source IN ('Stacks Project','ProofWiki','An Infinitely Large Napkin','CRing Project','HoTT Book','Open Logic Project')"
    python -m pipeline.generate_embeddings -m qwen3-8b \\
        -c "paper.source IN (...same list...)"

Mapping
-------
- Papers keep v1's granularity (Stacks and textbook chapters, ProofWiki as
  one project): textbook numbering restarts per chapter, so merging chapters
  would make refs like "Theorem 1.1" ambiguous. external_id = v1 paper_id.
- kind: Stacks / ProofWiki -> open_project; the textbooks -> textbook.
- "Lemma 46.3.3." -> kind lemma, ref "46.3.3"; "Theorem 2.8. (Title)" ->
  ref "2.8", note "Title". ProofWiki statements are named by page title,
  used as both ref and note.
- informal_metadata.url holds the per-statement link where the source has
  one (Stacks tags, ProofWiki pages); the textbooks link only to their PDF,
  which is the paper url.

Usage
-----
    python rds/scripts/ingest_v1_sources.py            # dry run: counts + samples, no writes
    python rds/scripts/ingest_v1_sources.py --apply    # write (skips papers that already have statements)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from collections import defaultdict

from psycopg2.extras import execute_values

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.connect import get_rds_connection

SOURCES = {
    # v1 source name       -> v2 paper.kind
    "Stacks Project":             "open_project",
    "ProofWiki":                  "open_project",
    "An Infinitely Large Napkin": "textbook",
    "CRing Project":              "textbook",
    "HoTT Book":                  "textbook",
    "Open Logic Project":         "textbook",
}
# Sources whose v1 per-theorem link points at that statement (not the whole book).
PER_STATEMENT_LINKS = {"Stacks Project", "ProofWiki"}

_NAME_RE = re.compile(
    r"^(?P<kind>[A-Za-z]+)\s+(?P<ref>[0-9A-Za-z.]+?)\.?(?:\s+\((?P<note>.*)\))?\s*$"
)

_V1_SQL = """
SELECT q.source, q.paper_id, q.theorem_id, q.theorem_name, q.theorem_type, q.theorem_body,
       q.link AS theorem_link, t.label,
       p.title, p.authors, p.link AS paper_link, p.categories, p.last_updated
FROM theorem_search_qwen8b q
JOIN theorem t ON t.theorem_id = q.theorem_id
JOIN paper p   ON p.paper_id = q.paper_id
WHERE q.source = ANY(%s)
"""

_ADD_URL_COLUMN = "ALTER TABLE informal_metadata ADD COLUMN IF NOT EXISTS url TEXT"


def parse_name(source: str, name: str) -> tuple[str | None, str | None]:
    """(ref, note) from a v1 theorem name."""
    name = (name or "").strip()
    if source == "ProofWiki":
        return name or None, name or None
    m = _NAME_RE.match(name)
    if not m:
        return None, name or None
    return m.group("ref"), m.group("note")


def load_v1() -> dict[tuple[str, str], dict]:
    """v1 rows grouped into papers, statements in document (theorem_id) order."""
    conn = get_rds_connection("postgres")
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = 0")
        cur.execute(_V1_SQL, (list(SOURCES),))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()

    papers: dict[tuple[str, str], dict] = {}
    seen = defaultdict(set)
    for r in sorted(rows, key=lambda r: (r["source"], r["paper_id"], r["theorem_id"])):
        key = (r["source"], r["paper_id"])
        if r["theorem_id"] in seen[key]:
            continue  # one v1 row per slogan; keep one per theorem
        seen[key].add(r["theorem_id"])
        paper = papers.setdefault(key, {
            "source": r["source"],
            "kind": SOURCES[r["source"]],
            "external_id": r["paper_id"],
            "title": r["title"],
            "authors": r["authors"] or [],
            "url": r["paper_link"],
            "categories": r["categories"] or [],
            "updated_at": r["last_updated"],
            "statements": [],
        })
        ref, note = parse_name(r["source"], r["theorem_name"])
        paper["statements"].append({
            "kind": (r["theorem_type"] or "theorem").lower(),
            "body": r["theorem_body"],
            "ref": ref,
            "note": note,
            "label": r["label"],
            "url": r["theorem_link"] if r["source"] in PER_STATEMENT_LINKS else None,
        })
    return papers


def apply(papers: dict[tuple[str, str], dict]) -> None:
    conn = get_rds_connection("v2")
    with conn.cursor() as cur:
        # Nullable column without default: a catalog-only change, but it still
        # needs a brief exclusive lock, so don't queue behind long queries.
        cur.execute("SET LOCAL lock_timeout = '10s'")
        cur.execute(_ADD_URL_COLUMN)
    conn.commit()

    by_source = defaultdict(list)
    for p in papers.values():
        by_source[p["source"]].append(p)

    for source, plist in sorted(by_source.items()):
        n_new_papers = n_statements = n_skipped = 0
        with conn.cursor() as cur:
            for p in plist:
                cur.execute(
                    """
                    INSERT INTO paper (kind, source, title, authors, url, external_id, categories, updated_at)
                    VALUES (%(kind)s, %(source)s, %(title)s, %(authors)s, %(url)s,
                            %(external_id)s, %(categories)s, %(updated_at)s)
                    ON CONFLICT (source, external_id) DO UPDATE
                        SET kind = EXCLUDED.kind, title = EXCLUDED.title, authors = EXCLUDED.authors,
                            url = EXCLUDED.url, categories = EXCLUDED.categories
                    RETURNING paper_id, (xmax = 0) AS inserted
                    """,
                    p,
                )
                paper_id, inserted = cur.fetchone()
                n_new_papers += inserted
                cur.execute("SELECT EXISTS (SELECT 1 FROM statement WHERE paper_id = %s)", (paper_id,))
                if cur.fetchone()[0]:
                    n_skipped += 1
                    continue
                ids = [uuid.uuid4() for _ in p["statements"]]
                execute_values(
                    cur,
                    "INSERT INTO statement (statement_id, paper_id, formality, kind, body) VALUES %s",
                    [(str(i), paper_id, "informal", s["kind"], s["body"]) for i, s in zip(ids, p["statements"])],
                )
                execute_values(
                    cur,
                    "INSERT INTO informal_metadata (statement_id, ordinal, ref, label, note, url) VALUES %s",
                    [(str(i), n, s["ref"], s["label"], s["note"], s["url"])
                     for n, (i, s) in enumerate(zip(ids, p["statements"]))],
                )
                n_statements += len(ids)
        conn.commit()
        print(f"  {source:28s} papers: {len(plist):>4} ({n_new_papers} new, {n_skipped} already had statements)"
              f"  statements inserted: {n_statements:>6,}")
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Write to v2. Default: dry run.")
    args = parser.parse_args()

    print("Reading v1 ...")
    papers = load_v1()
    per_source = defaultdict(lambda: [0, 0, 0])
    for p in papers.values():
        c = per_source[p["source"]]
        c[0] += 1
        c[1] += len(p["statements"])
        c[2] += sum(s["ref"] is None for s in p["statements"])
    for source, (np, ns, noref) in sorted(per_source.items()):
        print(f"  {source:28s} papers: {np:>4}  statements: {ns:>6,}  without ref: {noref}")
        sample = next(p for p in papers.values() if p["source"] == source)
        s = sample["statements"][0]
        print(f"      e.g. paper {sample['external_id']!r} ({sample['kind']}, {sample['title']!r}, url={sample['url']})")
        print(f"           {s['kind']} ref={s['ref']!r} note={s['note']!r} label={s['label']!r} url={s['url']}")

    if not args.apply:
        print("\nDry run; nothing written. Re-run with --apply to write.")
        return
    print("\nWriting to v2 ...")
    apply(papers)


if __name__ == "__main__":
    main()
