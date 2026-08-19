"""Token/cost accounting — the first in either repo, kept self-contained.

The primary metric is sorry-free proof rate PER DOLLAR, so every LLM and embedding
call must be metered. Prices are $/1M tokens; verify against the current price sheet
before a frozen run and record the table in the run manifest (run_experiment.py does).

Usage:
    meter = CostMeter()
    resp = client.messages.create(...)
    cost = meter.record_anthropic(model, resp.usage.input_tokens, resp.usage.output_tokens)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# $/1M input, $/1M output. Anthropic first-party API rates as of 2026-08.
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# Nebius Qwen3-Embedding-8B, $/1M input tokens; override if the price sheet moved.
EMBED_PRICE_PER_MTOK = float(os.environ.get("GP_EMBED_PRICE_PER_MTOK", "0.01"))


@dataclass
class CostMeter:
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    embed_tokens: int = 0
    usd: float = 0.0
    by_model: dict = field(default_factory=dict)

    def record_anthropic(self, model: str, input_tokens: int, output_tokens: int) -> float:
        if model not in PRICES:
            raise KeyError(f"no price for model {model!r} — add it to costs.PRICES")
        pin, pout = PRICES[model]
        cost = input_tokens * pin / 1e6 + output_tokens * pout / 1e6
        self.llm_input_tokens += input_tokens
        self.llm_output_tokens += output_tokens
        self.usd += cost
        m = self.by_model.setdefault(model, {"input": 0, "output": 0, "usd": 0.0})
        m["input"] += input_tokens
        m["output"] += output_tokens
        m["usd"] += cost
        return cost

    def record_embedding(self, tokens: int) -> float:
        cost = tokens * EMBED_PRICE_PER_MTOK / 1e6
        self.embed_tokens += tokens
        self.usd += cost
        return cost

    def snapshot(self) -> dict:
        return {"llm_input_tokens": self.llm_input_tokens,
                "llm_output_tokens": self.llm_output_tokens,
                "embed_tokens": self.embed_tokens,
                "usd": round(self.usd, 6),
                "by_model": self.by_model}
