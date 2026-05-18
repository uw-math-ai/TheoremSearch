import json
import os
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
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


class LocalEncoder:
    """sentence-transformers encoder running on cpu or cuda."""

    def __init__(self, model_config: Dict[str, Any], device: str):
        import torch
        from sentence_transformers import SentenceTransformer

        kwargs: Dict[str, Any] = {"device": device}
        if device == "cuda":
            kwargs["model_kwargs"] = {"torch_dtype": torch.float16}
        self._model = SentenceTransformer(model_config["model"], **kwargs)

    def encode(self, texts, instruction, batch_size, normalize):
        return self._model.encode(
            texts,
            prompt=instruction,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=normalize,
        )


class NebiusEncoder:
    """Remote embedding via Nebius's OpenAI-compatible endpoint."""

    def __init__(self, model_config: Dict[str, Any]):
        from openai import OpenAI

        self._client = OpenAI(
            api_key=os.environ["NEBIUS_API_KEY"],
            base_url="https://api.studio.nebius.ai/v1/",
        )
        self._model = model_config["model"]

    def encode(self, texts, instruction, batch_size, normalize):
        inputs = (
            [f"{instruction}{t}" for t in texts] if instruction else list(texts)
        )
        vecs: List[np.ndarray] = []
        for start in range(0, len(inputs), batch_size):
            chunk = inputs[start:start + batch_size]
            resp = self._client.embeddings.create(model=self._model, input=chunk)
            vecs.extend(np.asarray(d.embedding, dtype=np.float32) for d in resp.data)
        arr = np.stack(vecs)
        if normalize:
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            arr = arr / np.where(norms == 0, 1, norms)
        return arr


def make_encoder(model_config: Dict[str, Any], device: str):
    """device: 'nebius' | 'cpu' | 'gpu'."""
    if device == "nebius":
        return NebiusEncoder(model_config)
    if device == "cpu":
        return LocalEncoder(model_config, device="cpu")
    if device == "gpu":
        return LocalEncoder(model_config, device="cuda")
    raise ValueError(f"--device must be one of 'nebius', 'cpu', 'gpu'; got {device!r}")


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
