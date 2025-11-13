from ..rds.connect import get_rds_connection
from ..rds.paginate import paginate_query
from .embeddings import get_embedder, embed_texts
import argparse

# TODO: Allow user to filter which slogans get embedded

conn = get_rds_connection()
embedder = get_embedder()

def generate_embeddings(
    page_size: int = 128,
    batch_size: int = 16,
    overwrite: bool = False
):
    base_sql = """
        SELECT slogan_id, slogan
        FROM theorem_slogan
    """
    count_sql = """
        SELECT COUNT(*)
        FROM theorem_slogan
    """

    if not overwrite:
        where_condition = """
            WHERE NOT EXISTS (
                SELECT 1
                FROM theorem_embedding_qwen AS teq
                WHERE teq.slogan_id = theorem_slogan.slogan_id
            )
        """

        base_sql += " " + where_condition
        count_sql += " " + where_condition

    with conn.cursor() as cur:
        cur.execute(count_sql)
        n_results = cur.fetchone()[0]

    print(f"Generating embeddings for {n_results} matching slogans:")
    n_slogans = 0

    for page_index, slogans in enumerate(paginate_query(
        conn,
        base_sql=base_sql,
        base_params=(),
        order_by="slogan_id",
        descending=False,
        page_size=page_size
    )):
        n_slogans += len(slogans)
        print(f" > Page {page_index + 1}: {n_slogans}/{n_results}")

        embeddings = embed_texts(
            embedder,
            [s["slogan"] for s in slogans],
            batch_size=batch_size
        )

        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO theorem_embedding_qwen (slogan_id, embedding)
                VALUES (%s, %s)
                ON CONFLICT (slogan_id) DO UPDATE
                SET embedding = EXCLUDED.embedding
            """, [(s["slogan_id"], e) for s, e in zip(slogans, embeddings)]) 

        conn.commit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

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
        page_size=args.page_size,
        batch_size=args.batch_size,
        overwrite=args.overwrite
    )