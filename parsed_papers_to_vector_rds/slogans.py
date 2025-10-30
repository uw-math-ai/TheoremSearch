"""
Helpers for converting theorems into slogans.
"""

import os, json
from typing import List
from pydantic import BaseModel, Field
from concurrent.futures import ThreadPoolExecutor, as_completed
import instructor
from litellm import completion

client = instructor.from_litellm(completion)

class Slogan(BaseModel):
    id: str = Field(..., description="ID of the theorem")
    summary: str = Field(..., description="<= 4 sentence ASCII brief summary")

class TheoremSlogans(BaseModel):
    slogans: List[Slogan]

def _chunks(items, batch_size=10):
    for i in range(0, len(items), batch_size):
        yield items[i:i+batch_size]

def _generate_theorem_slogans_batch(client, theorem_batch, global_context: str) -> List[str]:
    theorems_json = {
        "theorems": theorem_batch
    }
    
    PROMPT = (
        "You generate accurate summaries of math theorems. "
        "Your summaries must be accurate, brief, and <= 4 sentences. "
        "Summaries have no formatting, just sentences in ASCII with no Unicode. "
        "Describe but never reference the theorems with 'This theorem...' or similar. "
        "Keep LateX minimal. Include identifiers that aid retrieval. "
        "Summaries output must correspond with theorems input by ID. "
    )

    try:
        res = client.chat.completions.create(
            model="deepseek/deepseek-chat",
            response_model=TheoremSlogans,
            messages=[
                {
                    "role": "user",
                    "content": PROMPT
                },
                {
                    "role": "user",
                    "content": json.dumps(theorems_json)
                }
            ]
        )
        
        slogans_json = res.parsed
    except Exception as e:
        print(f"Chat completions error: {e}")

        return {}
    
    id_to_slogan = {
        slogan_with_id.id: slogan_with_id.summary
        for slogan_with_id in slogans_json.slogans
    }

    return id_to_slogan

def generate_theorem_slogans(
    theorems: List[str], 
    global_context: str, 
    max_retries=4,
    max_workers=5,
    batch_size=10
) -> List[str]:
    id_to_slogan = {}
    
    theorems_left = [
        {
            "id": str(i),
            "theorem": theorem
        }
        for i, theorem in enumerate(theorems)
    ]

    retries = 0

    while True:
        if not theorems_left:
            break
        if retries > max_retries:
            raise ValueError("Max retries (6) reached for slogan generation.")

        retries += 1

        theorem_batches = list(_chunks(theorems_left, batch_size))

        with ThreadPoolExecutor(max_workers) as ex:
            futs = {
                ex.submit(_generate_theorem_slogans_batch, client, batch, global_context)
                for batch in theorem_batches
            }
            for fut in as_completed(futs):
                id_to_slogan.update(fut.result())

        theorems_left_orig = theorems_left.copy()
        theorems_left = []

        for theorem_left in theorems_left_orig:
            if theorem_left["id"] not in id_to_slogan:
                theorems_left.append(theorem_left)

    return [id_to_slogan[str(i)] for i in range(len(theorems))]