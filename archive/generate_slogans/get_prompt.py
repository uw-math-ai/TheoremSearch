import json
from pathlib import Path
from typing import Dict, Any, List
from .types import SloganPrompt

PROMPTS_DIR = Path("ec2/slogan_prompts")

def _validate_prompt_json(prompt_json: Any, prompt_id: str):
    if "id" in prompt_json:
        if prompt_json["id"] != prompt_id:
            raise ValueError(f"Prompt ID in prompt file, '{prompt_json['id']}' does not match given ID '{prompt_id}'")
    else:
        raise ValueError("Prompt file doesn't have an `id`")
    
    if "instructions" not in prompt_json:
        raise ValueError("Prompt file doesn't have `instructions`")
    
    if "context" in prompt_json:
        contexts: List[str] = prompt_json["context"]
        for c in contexts:
            if not (c.startswith("theorem.") or c.startswith("paper.")):
                raise ValueError(f"`context` '{c}' does not reference `theorem` nor `paper`")
    else:
        raise ValueError("Prompt file doesn't have a `context`")
    
    if "temperature" in prompt_json:
        temperature = prompt_json["temperature"]
        if not (0 <= temperature <= 1):
            raise ValueError(f"`temperature` must be between 0 and 1, not {temperature}") 
    else:
        raise ValueError("Prompt file doesn't have a `temperature`")
    
    if "max_tokens" in prompt_json:
        max_tokens = prompt_json["max_tokens"]
        if max_tokens <= 0:
            raise ValueError(f"`max_tokens` must be positive, not {max_tokens}")
    else:
        raise ValueError("Prompt file doesn't have a `max_tokens`")

def get_prompt(prompt_id: str) -> SloganPrompt:
    """
    Given a prompt ID, gets the corresponding SloganPrompt. Also validates the contents of the
    prompt file are valid.

    Parameters
    ----------
    prompt_id : str
        The ID of the prompt

    Returns
    -------
    prompt : SloganPrompt
        The prompt object
    """

    prompt_file = PROMPTS_DIR / (prompt_id + ".prompt")

    if not prompt_file.exists():
        raise FileNotFoundError(f"Slogan prompt file '{prompt_id}.prompt' not found")
    
    prompt_json: Dict = json.loads(prompt_file.read_text())

    _validate_prompt_json(prompt_json, prompt_id)

    return {
        "id": prompt_json["id"],
        "instructions": " ".join(prompt_json["instructions"]),
        "context": prompt_json["context"],
        "temperature": prompt_json["temperature"],
        "max_tokens": prompt_json["max_tokens"]
    }