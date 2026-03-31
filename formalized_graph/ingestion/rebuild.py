from __future__ import annotations

import json
import sqlite3
import sys
import os
from pathlib import Path
from tqdm import tqdm
from loguru import logger

def clean_path(p: str) -> str:
    if not p: return ""
    # Strip absolute workspace path if present
    workspace_prefix = "/Users/simon/Desktop/math lab/TheoremSearch/formalized_graph/"
    if p.startswith(workspace_prefix):
        p = p[len(workspace_prefix):]
        
    p = p.replace(".lake/packages/mathlib/", "formalized_graph/data/mathlib/mathlib4/")
    p = p.replace(".lake/packages/aesop/", "")
    p = p.replace(".lake/packages/std/", "")
    p = p.replace(".lake/build/ir/", "")
    p = p.replace(".lake/build/lib/lean/", "")
    p = p.replace("build/lib/lean/", "")
    p = p.replace(".ast.json", ".lean")
    if p.startswith("./"): p = p[2:]
    return p

def get_project_id(db, name: str) -> int:
    row = db.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
    if row: return row[0]
    db.execute("INSERT INTO projects (name, is_mathlib) VALUES (?, ?)", (name, 1 if name == 'Mathlib' else 0))
    return db.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()[0]

def log_db_state(db_path: Path, cursor: sqlite3.Cursor, stage: str):
    db_size = os.path.getsize(db_path) / (1024 * 1024)
    nodes = cursor.execute("SELECT COUNT(*) FROM nodes;").fetchone()[0]
    edges = cursor.execute("SELECT COUNT(*) FROM edges;").fetchone()[0]
    logger.info(f"--- STATE: {stage} ---")
    logger.info(f"DB Size: {db_size:.2f} MB")
    logger.info(f"Nodes: {nodes:,}")
    logger.info(f"Edges: {edges:,}")
    logger.info("-" * 25)

def rebuild_database():
    # Anchor all paths to the repo root, regardless of cwd.
    repo_root = Path(__file__).parent.parent
    data_dir  = repo_root / "data"
    db_path   = data_dir / "generated" / "global_corpus.db"

    logger.info(f"Repo root: {repo_root}")
    logger.info(f"Connecting to database at {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Verify State Before
    log_db_state(db_path, cursor, "BEFORE WIPE")

    # 1. Wipe and Prepare
    logger.info("Wiping existing nodes and edges...")
    cursor.execute("DELETE FROM edges;")
    cursor.execute("DELETE FROM nodes;")
    conn.commit()

    # Verify State After Wipe
    log_db_state(db_path, cursor, "AFTER WIPE")

    mathlib_id = get_project_id(cursor, "Mathlib")

    # 2. Gather all AST JSONs from known data directories
    ast_files = []
    mathlib_dir = data_dir / "mathlib" / "mathlib4"
    if mathlib_dir.exists():
        ast_files += list(mathlib_dir.rglob("*.ast.json"))
    else:
        logger.warning(f"Mathlib not found at {mathlib_dir}")

    projects_dir = data_dir / "formalization_projects"
    project_ids: dict[str, int] = {"Mathlib": mathlib_id}
    if projects_dir.exists():
        for project_dir in projects_dir.iterdir():
            if project_dir.is_dir():
                project_ids[project_dir.name] = get_project_id(cursor, project_dir.name)
                ast_files += list(project_dir.rglob("*.ast.json"))

    if not ast_files:
        logger.error("No AST files found — aborting to avoid wiping DB with empty data.")
        conn.close()
        return

    logger.info(f"Found {len(ast_files)} AST files. Starting Phase 1: Nodes.")

    # Phase 1: Populate Nodes Correctly
    nodes_batch = []
    seen_nodes = set()

    for ast_path in tqdm(ast_files, desc="Extracting Nodes"):
        try:
            with open(ast_path) as f:
                data = json.load(f)
            
            for p in data.get("premises", []):
                name = p["fullName"]
                if name in seen_nodes:
                    continue
                
                raw_def_path = p.get("defPath", "")
                c_path = clean_path(raw_def_path)
                
                # Assign project by matching path against known project directories
                proj_id = mathlib_id
                for proj_name, pid in project_ids.items():
                    if proj_name != "Mathlib" and f"formalization_projects/{proj_name}" in c_path:
                        proj_id = pid
                        break
                
                nodes_batch.append((proj_id, name, "unknown", c_path, "", ""))
                seen_nodes.add(name)

                if len(nodes_batch) >= 10000:
                    cursor.executemany("""
                        INSERT OR IGNORE INTO nodes (project_id, full_name, kind, file_path, docstring, statement)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, nodes_batch)
                    nodes_batch = []
        except Exception:
            pass

    if nodes_batch:
        cursor.executemany("""
            INSERT OR IGNORE INTO nodes (project_id, full_name, kind, file_path, docstring, statement)
            VALUES (?, ?, ?, ?, ?, ?)
        """, nodes_batch)
    conn.commit()

    cursor.execute("SELECT full_name, id FROM nodes")
    name_to_id = {row[0]: row[1] for row in cursor.fetchall()}
    logger.success(f"Populated {len(name_to_id)} correct nodes.")

    # Phase 2: Global pre-scan — build exact intervals from defPos/defEndPos across ALL ASTs.
    # This fixes the bug where theorems never referenced within their own file got no interval,
    # causing their edges to be misattributed to the preceding definition.
    logger.info("Phase 2a: Building global definition intervals from all ASTs...")
    # file_path -> {full_name -> (start_line, end_line)}
    global_intervals: dict[str, dict[str, tuple[int, int]]] = {}

    for ast_path in tqdm(ast_files, desc="Pre-scanning intervals"):
        try:
            with open(ast_path) as f:
                data = json.load(f)
            for p in data.get("premises", []):
                def_path = clean_path(p.get("defPath", ""))
                def_pos = p.get("defPos")
                def_end_pos = p.get("defEndPos")
                if not def_path or not def_pos or not def_end_pos:
                    continue
                name = p["fullName"]
                start = def_pos["line"]
                end = def_end_pos["line"]
                if def_path not in global_intervals:
                    global_intervals[def_path] = {}
                # Keep the entry with the largest end line (most complete range seen)
                existing = global_intervals[def_path].get(name)
                if existing is None or end > existing[1]:
                    global_intervals[def_path][name] = (start, end)
        except Exception as e:
            logger.error(f"Error pre-scanning {ast_path}: {e}")

    logger.success(f"Pre-scan complete: {sum(len(v) for v in global_intervals.values()):,} definition intervals across {len(global_intervals):,} files.")

    # Phase 2b: Build edges using exact intervals
    all_edges = []

    for ast_path in tqdm(ast_files, desc="Rebuilding Edges (Interval Logic)"):
        try:
            with open(ast_path) as f:
                data = json.load(f)

            premises = data.get("premises", [])
            rel_path = clean_path(str(ast_path))

            file_def_map = global_intervals.get(rel_path, {})
            if not file_def_map:
                continue

            intervals = []
            for name, (start, end) in file_def_map.items():
                nid = name_to_id.get(name)
                if nid:
                    intervals.append((start, end, nid))
            intervals.sort(key=lambda x: x[0])

            file_edges = {}

            for p in premises:
                target_id = name_to_id.get(p["fullName"])
                if not target_id:
                    continue
                usage_pos = p.get("pos")
                if not usage_pos:
                    continue
                u_line = usage_pos["line"]

                owner_id = None
                for start_line, end_line, oid in intervals:
                    if start_line <= u_line <= end_line:
                        owner_id = oid
                        break

                if owner_id and owner_id != target_id:
                    is_implicit = 0 if p.get("isDirect") else 1
                    edge_key = (owner_id, target_id)
                    if edge_key not in file_edges or is_implicit == 0:
                        file_edges[edge_key] = is_implicit

            for (sid, tid), imp in file_edges.items():
                all_edges.append((sid, tid, imp, "compiler_trace"))

            if len(all_edges) >= 50000:
                cursor.executemany("INSERT OR IGNORE INTO edges (source_id, target_id, is_implicit, tactic_context) VALUES (?, ?, ?, ?)", all_edges)
                conn.commit()
                all_edges = []

        except Exception as e:
            logger.error(f"Error processing {ast_path}: {e}")

    if all_edges:
        cursor.executemany("INSERT OR IGNORE INTO edges (source_id, target_id, is_implicit, tactic_context) VALUES (?, ?, ?, ?)", all_edges)
        conn.commit()

    # Recalculate Degrees
    logger.info("Recalculating node degrees...")
    cursor.execute("UPDATE nodes SET in_degree = 0, out_degree = 0")
    cursor.execute("""
        UPDATE nodes SET 
        in_degree = (SELECT COUNT(*) FROM edges WHERE target_id = nodes.id AND is_implicit = 0),
        out_degree = (SELECT COUNT(*) FROM edges WHERE source_id = nodes.id AND is_implicit = 0)
    """)
    conn.commit()

    # Verify State Final
    log_db_state(db_path, cursor, "FINAL VERIFIED REBUILD")

    logger.success("✅ Fast Rebuild Complete.")
    conn.close()

if __name__ == "__main__":
    rebuild_database()
