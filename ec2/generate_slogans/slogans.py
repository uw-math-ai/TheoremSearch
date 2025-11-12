from litellm import completion, completion_cost
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from .cost import format_USD

def _generate_theorem_slogan(
    instructions: str,
    theorem_context: dict,
    model: str,
    i: int
) -> tuple[int, str, float]:
    theorem_context = theorem_context.copy()
    if "theorem_id" in theorem_context:
        del theorem_context["theorem_id"]

    cost = 0

    try:
        theorem_context_str = json.dumps(theorem_context)

        messages = [
            {
                "role": "user",
                "content": instructions
            },
            {
                "role": "user",
                "content": theorem_context_str
            }
        ]

        res = completion(
            model=model,
            messages=messages
        )

        slogan = res.choices[0].message["content"]

        cost += completion_cost(res)

        return i, slogan, cost 
    except Exception as e:
        return i, None, cost

def generate_theorem_slogans(
    theorem_contexts: list[dict],
    instructions: str,
    model: str,
    max_workers=16,
    max_retries=4
) -> list[str | None]:
    slogans = [None for _ in theorem_contexts]
    retries = 0

    total_cost = 0
    slogans_generated = 0

    with ThreadPoolExecutor(max_workers) as ex, tqdm(total=len(theorem_contexts)) as pbar:
        while None in slogans:
            if retries > max_retries:
                break

            futs = {
                ex.submit(_generate_theorem_slogan, instructions, theorem_context, model, i)
                for i, theorem_context in enumerate(theorem_contexts)
                if slogans[i] is None
            }
            for fut in as_completed(futs):
                res = fut.result()
                slogans[res[0]] = res[1]
                total_cost += res[2]

                if res[1] is not None:
                    pbar.update(1)
                    slogans_generated += 1
                
                pbar.set_postfix({
                    "cost": format_USD(total_cost), 
                    "avg": format_USD(0 if slogans_generated == 0 else total_cost / slogans_generated)
                })

            retries += 1

    return slogans

    



