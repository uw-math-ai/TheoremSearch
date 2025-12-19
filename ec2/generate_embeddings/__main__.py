from ..rds.connect import get_rds_connection
from ..rds.paginate import paginate_query
from .embeddings import get_embedder, embed_texts
import argparse
from ..rds.upsert import upsert_rows
from .embedders import EMBEDDERS
from ..rds.query import build_query
from tqdm import tqdm

def generate_embeddings(
    embedder_alias: str,
    min_citations: int,
    in_journal: bool,
    page_size: int,
    batch_size: int,
    overwrite: bool,
    condition: bool
):
    conn = get_rds_connection()
    embedder = get_embedder(embedder_alias)

    query, params = build_query(
        base_query="""
            SELECT slogan_id, slogan
            FROM theorem_slogan
            INNER JOIN theorem
                ON theorem_slogan.theorem_id = theorem.theorem_id
            INNER JOIN paper
                ON theorem.paper_id = paper.paper_id
        """,
        where_clauses=[
            {
                "if": not overwrite,
                "condition": f"""
                    NOT EXISTS (
                        SELECT 1
                        FROM theorem_embedding_{embedder_alias} AS teq
                        WHERE teq.slogan_id = theorem_slogan.slogan_id
                    )
                """
            },
            {
                "if": min_citations >= 0,
                "condition": "paper.citations >= %s",
                "param": min_citations
            },
            {
                "if": in_journal,
                "condition": "paper.journal_ref IS NOT NULL",
            },
            {
                "if": condition,
                "condition": condition
            }
        ]
    )

    count_query = f"""
        SELECT COUNT(*)
        FROM ({query}) AS q
    """

    with conn.cursor() as cur:
        cur.execute(count_query, (*params,))
        count = cur.fetchone()[0]

    print(f"=== Generating embeddings for {count} slogans (Embedder: {EMBEDDERS[embedder_alias]}) ===")

    with tqdm(total=count, dynamic_ncols=True) as pbar:
        for slogans in paginate_query(
            conn,
            base_sql=query,
            base_params=(*params,),
            order_by="slogan_id",
            descending=False,
            page_size=page_size
        ):
            embeddings = embed_texts(
                embedder,
                [s["slogan"] for s in slogans],
                batch_size=batch_size
            )

            with conn.cursor() as cur:
                upsert_rows(
                    cur,
                    table=f"theorem_embedding_{embedder_alias}",
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

            pbar.update(len(embeddings))

    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--embedder",
        type=str,
        required=True,
        help="Alias (from EMBEDDERS.py) of HuggingFace embedder"
    )

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

    parser.add_argument(
        "--condition",
        type=str,
        required=False,
        default=""
    )

    args = parser.parse_args()

    generate_embeddings(
        embedder_alias=args.embedder,
        min_citations=args.min_citations,
        in_journal=args.in_journal,
        page_size=args.page_size,
        batch_size=args.batch_size,
        overwrite=args.overwrite,
        condition=args.condition
    )