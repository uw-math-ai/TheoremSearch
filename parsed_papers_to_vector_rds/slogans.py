"""
Helpers for converting theorems into slogans.
"""

import os, json
from typing import List
from google import genai
from pydantic import BaseModel, Field
from concurrent.futures import ThreadPoolExecutor, as_completed

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

class Slogan(BaseModel):
    id: str = Field(..., description="ID of the theorem")
    summary: str = Field(..., description="<= 4 sentence ASCII brief summary")

class TheoremSlogans(BaseModel):
    slogans: List[Slogan]

def _chunks(items, batch_size=4):
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
        "Summaries output must correspond with theorems input by ID.\n"
        "---\n"
        "**Input Theorems JSON:**\n"
        f"{json.dumps(theorems_json)}"
    )

    try:
        res = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=PROMPT,
            config={
                "response_mime_type": "application/json",
                "response_schema": TheoremSlogans
            }
        )
        
        slogans_json = res.parsed
    except Exception as e:
        print(f"An error occured: {e}")

        return []
    
    id_to_slogan = {
        slogan_with_id.id: slogan_with_id.summary
        for slogan_with_id in slogans_json.slogans
    }

    return id_to_slogan

def generate_theorem_slogans(theorems: List[str], global_context: str) -> List[str]:
    id_to_slogan = {}
    
    theorems_list = [
        {
            "id": str(i),
            "theorem": theorem
        }
        for i, theorem in enumerate(theorems)
    ]
    theorem_batches = list(_chunks(theorems_list, batch_size=6))

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {
            ex.submit(_generate_theorem_slogans_batch, client, batch, global_context)
            for batch in theorem_batches
        }
        for fut in as_completed(futs):
            id_to_slogan.update(fut.result())

    return [id_to_slogan[str(i)] for i in range(len(theorems))]