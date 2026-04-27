from __future__ import annotations

import yaml
from dataclasses import dataclass


@dataclass
class Config:
    model: str
    H: int
    k: int
    alpha: float
    beta: float
    concurrency: int
    match_threshold: float
    low_confidence_gap: float
    cache_dir: str
    data_cache_path: str
    results_dir: str
    system_prompt_path: str

    @classmethod
    def from_yaml(cls, path: str) -> Config:
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)
