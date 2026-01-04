"""
Script that generates embeddings for theorem slogans found in `theorem_slogan` table into the
`theorem_embedding_{embedder}` table.
"""

from ..rds.connect import get_rds_connection
from ..rds.paginate import paginate_query
from .embeddings import embed_texts
import argparse
from ..rds.upsert import upsert_rows
from ..rds.query import build_query, get_query_count
from tqdm import tqdm
from ..printing.scripts import print_script_header

def _generate_embeddings(
    embedder_alias: str,
    condition: bool,
    overwrite: bool,
    page_size: int,
    batch_size: int
):
    print_script_header(
        action="Generating embeddings for theorem slogans",
        params={
            "embedder": embedder_alias,
            "condition?": condition,
            "overwrite": overwrite,
            "page_size": page_size,
            "batch_size": batch_size
        }
    )

    conn = get_rds_connection()

    query, params = build_query(
        base_query="""
            SELECT slogan_id, slogan
            FROM theorem_slogan
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
                "if": condition,
                "condition": condition
            }
        ]
    )

    count = get_query_count(conn, query, params)

    with tqdm(total=count, dynamic_ncols=True) as pbar:
        for slogans in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="slogan_id",
            descending=False,
            page_size=page_size
        ):
            embeddings = embed_texts(
                embedder_alias,
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
        help="Alias (from `embedders.py`) of HuggingFace embedder"
    )

    parser.add_argument(
        "--condition",
        type=str,
        required=False,
        default="",
        help="SQL condition to filter theorem slogans on"
    )

    parser.add_argument(
        "-o", "--overwrite",
        action="store_true",
        help="Whether to overwrite embeddings. By default, False"
    )

    parser.add_argument(
        "--page-size",
        type=int,
        required=False,
        default=64,
        help="The number of theorem slogans queries per page. By default, 64"
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        required=False,
        default=8,
        help="The number of theorems slogans to embed in a batch. By default, 8"
    )

    args = parser.parse_args()

    _generate_embeddings(
        embedder_alias=args.embedder,
        condition=args.condition,
        overwrite=args.overwrite,
        page_size=args.page_size,
        batch_size=args.batch_size
    )