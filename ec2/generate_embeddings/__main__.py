from ..rds.connect import get_rds_connection
from ..rds.paginate import paginate_query
from .embeddings import get_embedder, embed_texts
import argparse
from ..rds.upsert import upsert_rows

conn = get_rds_connection()
embedder = get_embedder()

def generate_embeddings(
    min_citations: int,
    in_journal: bool,
    page_size: int,
    batch_size: int,
    overwrite: bool
):
    base_sql = """
        SELECT slogan_id, slogan
        FROM theorem_slogan
        INNER JOIN theorem
            ON theorem_slogan.theorem_id = theorem.theorem_id
        INNER JOIN paper
            ON theorem.paper_id = paper.paper_id
    """
    count_sql = """
        SELECT COUNT(*)
        FROM theorem_slogan
        INNER JOIN theorem
            ON theorem_slogan.theorem_id = theorem.theorem_id
        INNER JOIN paper
            ON theorem.paper_id = paper.paper_id
    """

    where_conditions = []
    base_params = []

    if not overwrite:
        where_conditions.append("""
            NOT EXISTS (
                SELECT 1
                FROM theorem_embedding_qwen AS teq
                WHERE teq.slogan_id = theorem_slogan.slogan_id
            )
        """)

    if min_citations >= 0:
        where_conditions.append("paper.citations >= %s")
        base_params.append(min_citations)

    if in_journal:
        where_conditions.append("paper.journal_ref IS NOT NULL")

    if where_conditions:
        base_sql += " WHERE " + " AND ".join(where_conditions)
        count_sql += " WHERE " + " AND ".join(where_conditions)

    with conn.cursor() as cur:
        cur.execute(count_sql)
        n_results = cur.fetchone()[0]

    print(f"=== Generating embeddings for {n_results} slogans (Embedder: Qwen/Qwen3-Embedding-0.6B) ===")
    n_slogans = 0

    for page_index, slogans in enumerate(paginate_query(
        conn,
        base_sql=base_sql,
        base_params=(*base_params,),
        order_by="slogan_id",
        descending=False,
        page_size=page_size
    )):
        n_slogans += len(slogans)
        print(f"[Page {page_index + 1}] {n_slogans}/{n_results}")

        embeddings = embed_texts(
            embedder,
            [s["slogan"] for s in slogans],
            batch_size=batch_size
        )

        with conn.cursor() as cur:
            upsert_rows(
                cur,
                table="theorem_embedding_qwen",
                rows=[
                    {
                        "slogan_id": slogan["slogan_id"],
                        "embedding": embedding
                    }
                    for slogan, embedding in zip(slogans, embeddings)
                ],
                on_conflict={
                    "with": ["slogan_id"],
                    "replace": ["embedding"]
                }
            )

        conn.commit()

    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--min-citations",
        type=int,
        required=False,
        default=-1,
        help="Minimum amount of citations on a paper to embed its theorem slogans"
    )

    parser.add_argument(
        "--in-journal",
        action="store_true",
        help="Whether to only embed theorem slogans from papers found in a journal"
    )

    parser.add_argument(
        "--page-size",
        type=int,
        required=False,
        default=128
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        required=False,
        default=16
    )

    parser.add_argument(
        "-o",
        "--overwrite"
    )

    args = parser.parse_args()

    generate_embeddings(
        min_citations=args.min_citations,
        in_journal=args.in_journal,
        page_size=args.page_size,
        batch_size=args.batch_size,
        overwrite=args.overwrite
    )