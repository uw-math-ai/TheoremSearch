from typing import Dict

"""
Available HuggingFace embedders. Formatted as
```
{
    alias: hugging_face_id
}
```
"""
EMBEDDERS: Dict[str, str] = {
    "qwen": "Qwen/Qwen3-Embedding-0.6B",
    "gemma": "google/embeddinggemma-300m",
    "qwen8b": "Qwen/Qwen3-Embedding-8B"
}