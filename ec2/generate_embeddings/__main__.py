from ..rds.connect import get_rds_connection
from ..rds.paginate import paginate_query
from .embeddings import embed_texts

# TODO: Allow user to filter which slogans get embedded

conn = get_rds_connection()

def generate_embeddings():
    for slogans in paginate_query(
        conn,
        base_sql="""
            SELECT slogan_id, slogan
            FROM theorem_slogan
        """,
        base_params=(),
        order_by="slogan_id",
        descending=False
    ):
        embeddings = embed_texts([s["slogan"] for s in slogans])

        for slogan, embedding in zip(slogans, embeddings):
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO theorem_embedding_qwen (slogan_id, embedding)
                    VALUES (%s, %s)
                    ON CONFLICT (slogan_id) DO UPDATE
                    SET
                        embedding = EXCLUDED.embedding
                """, (
                    slogan["slogan_id"],
                    embedding
                ))

        conn.commit()

if __name__ == "__main__":
    generate_embeddings()