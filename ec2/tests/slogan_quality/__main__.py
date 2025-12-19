"""
Uses a powerful (expensive) LLM API to rate the quality of a small sample of generated slogans. It
takes in as context the paper's PDF, the theorem (name and body), and the slogan and rates slogans
on a scale of 1 to 5.
"""

from argparse import ArgumentParser
from concurrent.futures import ProcessPoolExecutor, as_completed
from litellm import completion
from ...rds.connect import get_rds_connection
import json
from tqdm import tqdm


def _rate_one(args) -> float:
    model, paper_id, theorem_name, theorem_body, theorem_slogan = args

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "file",
                    "file": {
                        "file_id": f"https://arxiv.org/pdf/{paper_id}"
                    }
                },
                {
                    "type": "text",
                    "text": f"""
You are grading a slogan that is supposed to be a plain-English description of a theorem.
Use the theorem's name and LaTeX body to help locate the actual theorem in the PDF

Rate from 1-5:
5 = exact and precise
1 = wrong or unrelated

Theorem name:
{theorem_name}

Theorem body (LaTeX):
{theorem_body}

Slogan:
{theorem_slogan}

Return strict JSON:
{{"rating": int, "rationale": str}}
""".strip(),
                },
            ],
        }
    ]

    res = completion(
        model=model,
        messages=messages,
        temperature=0,
        response_format={"type": "json_object"},
    )

    content = res["choices"][0]["message"]["content"]
    content_json = json.loads(content)

    rating = float(content_json["rating"])

    if rating < 4:
        print(f"[POOR RATING ({rating})] {paper_id}, {theorem_name}: {content_json['rationale']}")

    return rating


def rate_slogans_quality(model: str, samples: int, workers: int) -> float:
    conn = get_rds_connection()
    ratings_sum = 0.0

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.paper_id, t.name, t.body, ts.slogan
            FROM theorem_slogan AS ts
            INNER JOIN theorem AS t ON t.theorem_id = ts.theorem_id
            WHERE t.parsing_method = 'tex' and ts.model = 'DeepSeek-V3.1'
            ORDER BY RANDOM()
            LIMIT %s
            """,
            (samples,),
        )
        rows = cur.fetchall()

    tasks = [(model, paper_id, theorem_name, theorem_body, theorem_slogan)
             for paper_id, theorem_name, theorem_body, theorem_slogan in rows]

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_rate_one, t) for t in tasks]

        for fut in tqdm(as_completed(futures), total=len(futures), dynamic_ncols=True):
            ratings_sum += fut.result()

    return ratings_sum


if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "--model",
        required=True,
        help="Expert model to use"
    )

    arg_parser.add_argument(
        "--samples",
        required=True,
        type=int,
        help="Number of samples to rate"
    )

    arg_parser.add_argument(
        "--workers",
        default=4,
        type=int,
        help="Number of processes"
    )

    args = arg_parser.parse_args()

    ratings_sum = rate_slogans_quality(
        model=args.model,
        samples=args.samples,
        workers=args.workers
    )

    print(f"average rating for {args.samples} slogans:", ratings_sum / args.samples)