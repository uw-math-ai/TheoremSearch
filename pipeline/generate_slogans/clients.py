"""Provider abstraction for online slogan generation.

Each ``LLMClient.complete(prompt, *, temperature, max_tokens)`` returns
``(text, usage)`` where ``usage`` is a dict shaped like
``{"prompt_tokens": int|None, "completion_tokens": int|None}``. That mirrors
the format the upsert pipeline already expects, so swapping providers is a
drop-in.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple


_USAGE_T = Dict[str, Optional[int]]


class LLMClient:
    def complete(
        self,
        prompt_text: str,
        *,
        temperature: float,
        max_tokens: int,
    ) -> Tuple[str, _USAGE_T]:
        raise NotImplementedError


class NebiusClient(LLMClient):
    """Nebius via OpenAI-compatible chat completions."""

    def __init__(self, model_id: str):
        from openai import OpenAI

        self._client = OpenAI(
            api_key=os.environ["NEBIUS_API_KEY"],
            base_url="https://api.studio.nebius.ai/v1/",
        )
        self._model_id = model_id

    def complete(self, prompt_text, *, temperature, max_tokens):
        resp = self._client.chat.completions.create(
            model=self._model_id,
            messages=[{"role": "user", "content": prompt_text}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        usage = resp.usage
        return resp.choices[0].message.content, {
            "prompt_tokens":     usage.prompt_tokens     if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
        }


class BedrockClient(LLMClient):
    """AWS Bedrock via the Converse API.

    Credentials resolve via boto3's default chain (env vars / instance
    profile / shared config). Region picked up from AWS_REGION /
    AWS_DEFAULT_REGION unless `region` is set in models.json.
    """

    def __init__(self, model_id: str, region: Optional[str] = None):
        import boto3

        self._client = boto3.client(
            "bedrock-runtime",
            region_name=region
            or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION"),
        )
        self._model_id = model_id

    def complete(self, prompt_text, *, temperature, max_tokens):
        resp = self._client.converse(
            modelId=self._model_id,
            messages=[{"role": "user", "content": [{"text": prompt_text}]}],
            inferenceConfig={
                "temperature": float(temperature),
                "maxTokens":   int(max_tokens),
            },
        )
        text = "".join(
            block["text"]
            for block in resp["output"]["message"]["content"]
            if "text" in block
        )
        usage = resp.get("usage") or {}
        return text, {
            "prompt_tokens":     usage.get("inputTokens"),
            "completion_tokens": usage.get("outputTokens"),
        }


def resolve_model_id(provider: str, model_config: Dict[str, Any]) -> str:
    """Return the provider-specific model identifier for this entry.

    Convention in models.json:
      - "model"          : the Nebius (default) model identifier.
      - "bedrock_model"  : optional override used when --provider bedrock.

    Slogans go in the DB keyed by the short logical name (e.g. "qwen3-235b"),
    so swapping providers doesn't duplicate rows — both producers write under
    the same model_name.
    """
    if provider == "nebius":
        return model_config["model"]
    if provider == "bedrock":
        bid = model_config.get("bedrock_model")
        if not bid:
            raise ValueError(
                "models.json entry has no 'bedrock_model' field; add it to use "
                "--provider bedrock."
            )
        return bid
    raise ValueError(f"Unknown provider: {provider!r}")


def make_client(
    provider: str,
    model_config: Dict[str, Any],
    region: Optional[str] = None,
) -> LLMClient:
    """Build a client routed to ``provider`` using the matching model ID.

    ``region`` (if given) overrides the models.json ``region`` entry; used to
    shard Bedrock traffic across regions for higher aggregate quota.
    """
    model_id = resolve_model_id(provider, model_config)
    if provider == "nebius":
        return NebiusClient(model_id)
    if provider == "bedrock":
        return BedrockClient(model_id, region=region or model_config.get("region"))
    raise ValueError(f"Unknown provider: {provider!r}")
