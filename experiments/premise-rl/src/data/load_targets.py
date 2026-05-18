from __future__ import annotations

import pickle
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

# connect.py lives at the premise-rl root; importable because Python adds the
# working directory to sys.path when running -m or pytest (pythonpath=["."])
from connect import get_rds_connection


@dataclass
class Target:
    statement_id: UUID
    body: str
    proof: str | None
    kind: str
    paper_id: UUID
    label: str | None
    ref: str | None
    pre_context: str | None
    post_context: str | None
    true_dep_ids: set[UUID] = field(default_factory=set)


@dataclass
class DepStatement:
    statement_id: UUID
    body: str
    kind: str
    paper_id: UUID


_SQL_TARGETS = """
SELECT s.statement_id, s.body, s.proof, s.kind, s.paper_id,
       im.label, im.ref, im.pre_context, im.post_context
FROM rl_test_100 t
JOIN statement s ON s.statement_id = t.src_id
LEFT JOIN informal_metadata im ON im.statement_id = s.statement_id;
"""

_SQL_DEPS = """
SELECT d.src_id, d.dep_id, d.cite_key, d.dep_name, d.dep_key
FROM informal_dependency d
JOIN rl_test_100 t ON t.src_id = d.src_id
WHERE d.cite_key IS NOT NULL
  AND d.method = 'deterministic'
  AND d.dep_id IS NOT NULL;
"""

_SQL_DEP_BODIES = """
SELECT DISTINCT s.statement_id, s.body, s.kind, s.paper_id
FROM informal_dependency d
JOIN rl_test_100 t ON t.src_id = d.src_id
JOIN statement s ON s.statement_id = d.dep_id
WHERE d.cite_key IS NOT NULL
  AND d.method = 'deterministic'
  AND d.dep_id IS NOT NULL;
"""


def _load_from_db() -> tuple[dict[UUID, Target], list[DepStatement]]:
    conn = get_rds_connection(db_name="v2")
    try:
        with conn.cursor() as cur:
            cur.execute(_SQL_TARGETS)
            targets: dict[UUID, Target] = {}
            for row in cur.fetchall():
                sid, body, proof, kind, paper_id, label, ref, pre_ctx, post_ctx = row
                targets[sid] = Target(
                    statement_id=sid,
                    body=body or "",
                    proof=proof,
                    kind=kind,
                    paper_id=paper_id,
                    label=label,
                    ref=ref,
                    pre_context=pre_ctx,
                    post_context=post_ctx,
                )

            cur.execute(_SQL_DEPS)
            for row in cur.fetchall():
                src_id, dep_id, _cite_key, _dep_name, _dep_key = row
                if src_id in targets:
                    targets[src_id].true_dep_ids.add(dep_id)

            cur.execute(_SQL_DEP_BODIES)
            dep_stmts: list[DepStatement] = []
            for row in cur.fetchall():
                sid, body, kind, paper_id = row
                dep_stmts.append(DepStatement(
                    statement_id=sid,
                    body=body or "",
                    kind=kind,
                    paper_id=paper_id,
                ))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return targets, dep_stmts


def load_all_data(
    cache_path: str | None = None,
) -> tuple[dict[UUID, Target], list[DepStatement]]:
    """Load target statements and dep bodies, with optional pickle cache."""
    if cache_path and Path(cache_path).exists():
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    targets, dep_stmts = _load_from_db()

    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "wb") as f:
            pickle.dump((targets, dep_stmts), f)

    return targets, dep_stmts


def print_checkpoint_stats(
    targets: dict[UUID, Target], dep_stmts: list[DepStatement]
) -> None:
    n_targets = len(targets)
    dep_counts = Counter(len(t.true_dep_ids) for t in targets.values())
    all_dep_ids = {d for t in targets.values() for d in t.true_dep_ids}

    print(f"Targets loaded:          {n_targets}")
    print(f"Dep count distribution:  {dict(sorted(dep_counts.items()))}")
    print(f"Total unique dep UUIDs:  {len(all_dep_ids)}")
    print(f"Dep statement bodies:    {len(dep_stmts)}")

    if n_targets != 100:
        print(f"WARNING: expected 100 targets, got {n_targets}")
    under = [sid for sid, t in targets.items() if len(t.true_dep_ids) < 2]
    if under:
        print(f"WARNING: {len(under)} targets have < 2 true deps — check SQL filter")


if __name__ == "__main__":
    _targets, _dep_stmts = load_all_data()
    print_checkpoint_stats(_targets, _dep_stmts)
