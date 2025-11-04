import instructor
from litellm import completion
from pydantic import BaseModel
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

client = instructor.from_litellm(completion)

class TheoremSlogan(BaseModel):
    slogan: str

def _generate_theorem_slogan(
    client, 
    instructions: str,
    theorem_context: dict,
    model: str,
    i: int
) -> tuple[int, str]:
    theorem_context = theorem_context.copy()

    del theorem_context["paper.paper_id"]
    del theorem_context["theorem.theorem_id"]

    try:
        res = client.chat.completions.create(
            model=model,
            response_model=TheoremSlogan,
            messages=[
                {
                    "role": "user",
                    "content": instructions
                },
                {
                    "role": "user",
                    "content": json.dumps(theorem_context)
                }
            ]
        )

        slogan = res.slogan

        return i, slogan
    except Exception as e:
        return i, None

def generate_theorem_slogans(
    theorem_contexts: list[dict],
    instructions: str,
    model: str,
    max_workers=16,
    max_retries=4
) -> list[str | None]:
    slogans = [None for _ in theorem_contexts]
    retries = 0

    with ThreadPoolExecutor(max_workers) as ex:
        while None in slogans:
            if retries > max_retries:
                break

            futs = {
                ex.submit(_generate_theorem_slogan, client, instructions, theorem_context, model, i)
                for i, theorem_context in enumerate(theorem_contexts)
                if slogans[i] is None
            }
            for fut in as_completed(futs):
                res = fut.result()
                slogans[res[0]] = res[1]

            retries += 1

    return slogans

    



