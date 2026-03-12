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
    db_path = Path("formalized_graph/data/generated/global_corpus.db")
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
    flt_id = get_project_id(cursor, "FLT")

    # 2. Gather all JSONs (Syntax Fixed)
    mathlib_asts = list(Path("formalized_graph/data/mathlib/mathlib4").rglob("*.ast.json"))
    flt_asts = list(Path("formalized_graph/data/formalization_projects/FLT").rglob("*.ast.json"))
    ast_files = mathlib_asts + flt_asts
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
                
                # Assign project
                proj_id = flt_id if "FLT" in c_path else mathlib_id
                
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

    # Phase 2: Edges with Interval Logic
    all_edges = []
    
    for ast_path in tqdm(ast_files, desc="Rebuilding Edges (Interval Logic)"):
        try:
            with open(ast_path) as f:
                data = json.load(f)
            
            premises = data.get("premises", [])
            rel_path = clean_path(str(ast_path))
            
            file_defs = []
            for p in premises:
                if clean_path(p.get("defPath", "")) == rel_path and p.get("defPos"):
                    file_defs.append({
                        "name": p["fullName"],
                        "line": p["defPos"]["line"]
                    })
            
            if not file_defs: continue
            
            file_defs.sort(key=lambda x: x["line"])
            
            intervals = []
            for i, d in enumerate(file_defs):
                start_line = d["line"]
                end_line = file_defs[i+1]["line"] - 1 if i + 1 < len(file_defs) else 9999999
                nid = name_to_id.get(d["name"])
                if nid:
                    intervals.append((start_line, end_line, nid))
            
            file_edges = {}
            
            for p in premises:
                target_id = name_to_id.get(p["fullName"])
                if not target_id: continue
                
                usage_pos = p.get("pos")
                if not usage_pos: continue
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
