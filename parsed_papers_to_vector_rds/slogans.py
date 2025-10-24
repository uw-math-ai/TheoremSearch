"""
Helpers for converting theorems into slogans.
"""

from openai import OpenAI
import os
from typing import List
from pydantic import BaseModel
import json

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class TheoremSlogans(BaseModel):
    slogans: List[str]

def generate_theorem_slogans(theorems: List[str], global_context: str) -> List[str]:
    """
    Converts a list of theorems and global_context into a list of accurate theorem slogans.

    Parameters
    ----------
    theorems: List[str]
        A list of theorem strings
    global_context: str
        A string describing notations, definitions, and assumptions shared across theorems.
    
    Returns
    -------
    slogans: List[str]
        A list of theorem slogans matching the length of theorems

    Raises
    ----------
        ValueError: If generated slogans list length doesn't match theorems list length
    """
    
    SYSTEM_MSG = (
        "You generate accurate summaries of all theorems. "
        "Summaries must be accurate and between 2-6 sentences. "
        "No formatting, just provide sentences. "
        "Keep LaTeX notation to a minimum, but never use unicode. "
        "You ensure relevant info is included that might be used to query the theorem. "
    )

    USER_INSTRUCTIONS = (
        "Return only JSON matching the schema. "
        "Input is a list of thorems. "
        "Please reference the global context and other theorems when making theorem slogans. "
    )

    user_input = {
        "instructions": USER_INSTRUCTIONS,
        "global_context": global_context,
        "theorems": theorems
    }

    res = client.responses.parse(
        model="gpt-5-mini",
        temperature=0,
        text_format=TheoremSlogans,
        input=[
            {"role": "system", "content": SYSTEM_MSG},
            {"role": "user", "content": json.dumps(user_input)}
        ]
    )

    slogans = res.output_parsed.slogans

    if len(slogans) != len(theorems):
        raise ValueError(f"Slogans length ({len(slogans)}) != theorems length ({len(theorems)})")
        
    return slogans