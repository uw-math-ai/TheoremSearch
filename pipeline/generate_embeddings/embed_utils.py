import json
from pathlib import Path
from typing import Any, Dict, Optional

from psycopg2.extensions import connection


MODELS_FILE = Path(__file__).parent / "models.json"


def load_model_config(name: str) -> Dict[str, Any]:
    """Load an embedding-model config by short name from models.json."""
    if not MODELS_FILE.exists():
        raise FileNotFoundError(f"models.json not found at {MODELS_FILE}")
    models = json.loads(MODELS_FILE.read_text())
    if name not in models:
        available = ", ".join(f'"{k}"' for k in models)
        raise ValueError(f"Model '{name}' not found in models.json. Available: {available}")
    return models[name]


def load_model(config: Dict[str, Any], device: Optional[str]):
    """
    Instantiate the sentence-transformers model. Uses CUDA if available (default)
    and loads in float16 on CUDA for speed/VRAM; falls back to float32 on CPU.
    """
    import torch
    from sentence_transformers import SentenceTransformer

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    kwargs: Dict[str, Any] = {"device": device}
    if device.startswith("cuda"):
        kwargs["model_kwargs"] = {"torch_dtype": torch.float16}

    return SentenceTransformer(config["model"], **kwargs)


def register_model(conn: connection, name: str, config: Dict[str, Any]) -> None:
    """
    Ensure this embedding model is registered in embedding_model.

    - New name → insert and commit.
    - Existing name, same config → no-op.
    - Existing name, different config → raise ValueError with rename guidance.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT model, instruction, dim, normalized FROM embedding_model WHERE name = %s",
            (name,),
        )
        row = cur.fetchone()

    normalized = bool(config.get("normalized", True))

    if row is None:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO embedding_model (name, model, instruction, dim, normalized) "
                "VALUES (%s, %s, %s, %s, %s)",
                (name, config["model"], config.get("instruction"), config["dim"], normalized),
            )
        conn.commit()
        return

    db_model, db_instr, db_dim, db_norm = row

    mismatches = []
    if db_model != config["model"]:
        mismatches.append(f"model ({db_model!r} → {config['model']!r})")
    if db_instr != config.get("instruction"):
        mismatches.append("instruction (changed)")
    if db_dim != config["dim"]:
        mismatches.append(f"dim ({db_dim} → {config['dim']})")
    if db_norm != normalized:
        mismatches.append(f"normalized ({db_norm} → {normalized})")

    if mismatches:
        raise ValueError(
            f"Model '{name}' exists in the database but models.json has changed: "
            + ", ".join(mismatches) + ".\n"
            f"Rename the entry (e.g. '{name}-v2') to register it as a new version."
        )
