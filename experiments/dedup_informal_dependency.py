"""
One-time dedup of informal_dependency, paper by paper.
Keeps one row per (src_id, dep_id) where dep_id IS NOT NULL,
by highest-priority method.
"""

import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
from rds.utils.connect import get_rds_connection


def main():
    conn = get_rds_connection("v2")

    with conn.cursor() as cur:
        cur.execute("SELECT paper_id FROM paper WHERE kind = 'paper'")
        paper_ids = [row[0] for row in cur.fetchall()]

    total_deleted = 0
    with tqdm(total=len(paper_ids), unit=" papers", desc="Deduping") as pbar:
        for paper_id in paper_ids:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM informal_dependency
                    WHERE dep_id IS NOT NULL
                      AND src_id IN (
                          SELECT statement_id FROM statement WHERE paper_id = %s
                      )
                      AND ctid IN (
                          SELECT ctid FROM (
                              SELECT ctid,
                                     ROW_NUMBER() OVER (
                                         PARTITION BY src_id, dep_id
                                         ORDER BY
                                             CASE
                                                 WHEN methods @> ARRAY['deterministic'] THEN 1
                                                 WHEN methods @> ARRAY['heuristic']     THEN 2
                                                 WHEN methods @> ARRAY['llm']           THEN 3
                                                 ELSE 4
                                             END,
                                             CASE WHEN cite_key IS NULL THEN 1 ELSE 2 END,
                                             CASE location
                                                 WHEN 'body'         THEN 1
                                                 WHEN 'proof'        THEN 2
                                                 WHEN 'note'         THEN 3
                                                 WHEN 'pre_context'  THEN 4
                                                 ELSE 5
                                             END
                                     ) AS rn
                              FROM informal_dependency
                              WHERE dep_id IS NOT NULL
                                AND src_id IN (
                                    SELECT statement_id FROM statement WHERE paper_id = %s
                                )
                          ) t
                          WHERE rn > 1
                      )
                """, (paper_id, paper_id))
                total_deleted += cur.rowcount
            conn.commit()
            pbar.set_postfix({"deleted": total_deleted})
            pbar.update(1)

    print(f"\nDone. {total_deleted:,} rows deleted.")
    conn.close()


if __name__ == "__main__":
    main()
