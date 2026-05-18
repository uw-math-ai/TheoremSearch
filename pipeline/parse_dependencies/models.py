import json
import os
from pathlib import Path

from openai import OpenAI

_MODELS_FILE = Path(__file__).parent / "models.json"


def load_model_config(name: str) -> dict:
    with open(_MODELS_FILE) as f:
        models = json.load(f)
    if name not in models:
        raise ValueError(f"Model '{name}' not in models.json. Available: {sorted(models)}")
    return models[name]


def build_openai_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["NEBIUS_API_KEY"],
        base_url="https://api.studio.nebius.ai/v1/",
    )
