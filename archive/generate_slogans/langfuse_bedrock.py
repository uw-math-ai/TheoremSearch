# This is a ChatGPT written helper file based on https://langfuse.com/integrations/model-providers/amazon-bedrock
# TODO: Rewrite for better documentation and utility

# bedrock.py
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from langfuse import get_client, observe


# -----------------------------
# Clients
# -----------------------------

_bedrock_runtime: Optional[BaseClient] = None
_langfuse = None


def get_bedrock_runtime(region_name: Optional[str] = None) -> BaseClient:
    """
    Returns a cached boto3 bedrock-runtime client.
    Uses AWS default credential provider chain (env vars, profiles, IAM roles, etc.).
    """
    global _bedrock_runtime
    if _bedrock_runtime is None:
        _bedrock_runtime = boto3.client(
            service_name="bedrock-runtime",
            region_name=region_name or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
        )
    return _bedrock_runtime


def get_langfuse():
    """
    Returns a cached Langfuse client (configured via env vars).
    - LANGFUSE_PUBLIC_KEY
    - LANGFUSE_SECRET_KEY
    - LANGFUSE_BASE_URL (optional)
    """
    global _langfuse
    if _langfuse is None:
        _langfuse = get_client()
    return _langfuse


def langfuse_auth_check(raise_on_fail: bool = True) -> bool:
    lf = get_langfuse()
    ok = bool(lf.auth_check())
    if raise_on_fail and not ok:
        raise RuntimeError("Langfuse auth_check() failed. Check LANGFUSE_* env vars.")
    return ok


# -----------------------------
# Converse wrapper (Langfuse pattern)
# -----------------------------

@observe(as_type="generation", name="Bedrock Converse")
def wrapped_bedrock_converse(
    *,
    modelId: str,
    messages: List[Dict[str, Any]],
    inferenceConfig: Optional[Dict[str, Any]] = None,
    additionalModelRequestFields: Optional[Dict[str, Any]] = None,
    region_name: Optional[str] = None,
    bedrock_runtime_client: Optional[BaseClient] = None,
    # free-form kwargs are forwarded to boto3 converse() (e.g., system, toolConfig, guardrailConfig, etc.)
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Calls Amazon Bedrock Runtime Converse API and reports a Langfuse generation.
    Returns the raw boto3 response.

    This implements the same core logic as the Langfuse Bedrock integration guide:
    1) Extract model metadata and update Langfuse generation input/model/params
    2) Call bedrock_runtime.converse() with error handling
    3) Update Langfuse generation with output + token usage + response metadata
    """
    lf = get_langfuse()

    # 1) Extract model parameters + metadata (mirrors guide)
    model_parameters: Dict[str, Any] = {}
    if inferenceConfig:
        model_parameters.update(inferenceConfig)
    if additionalModelRequestFields:
        model_parameters.update(additionalModelRequestFields)

    # store the "input" as the Bedrock messages structure
    lf.update_current_generation(
        input=messages,
        model=modelId,
        model_parameters=model_parameters,
        metadata={k: v for k, v in kwargs.items() if k not in ("bedrock_runtime_client", "region_name")},
    )

    # 2) Call Bedrock
    client = bedrock_runtime_client or get_bedrock_runtime(region_name=region_name)
    try:
        response = client.converse(
            modelId=modelId,
            messages=messages,
            inferenceConfig=inferenceConfig or {},
            additionalModelRequestFields=additionalModelRequestFields or {},
            **kwargs,
        )
    except (ClientError, Exception) as e:
        error_message = f"ERROR: Can't invoke '{modelId}' via Bedrock Converse. Reason: {e}"
        lf.update_current_generation(level="ERROR", status_message=error_message)
        raise

    # 3) Extract text + usage (mirrors guide)
    output_text = _extract_bedrock_converse_text(response)
    usage_details = _extract_bedrock_converse_usage(response)

    lf.update_current_generation(
        output=output_text,
        usage_details=usage_details,  # {"input": ..., "output": ..., "total": ...}
        metadata={"ResponseMetadata": response.get("ResponseMetadata", {})},
    )

    return response


def _extract_bedrock_converse_text(response: Dict[str, Any]) -> str:
    """
    Best-effort extraction of assistant text from Bedrock Converse response.
    Matches the common structure shown in Langfuse docs.
    """
    try:
        content = response["output"]["message"]["content"]
        # often: [{"text": "..."}]
        if isinstance(content, list) and content and isinstance(content[0], dict) and "text" in content[0]:
            return str(content[0]["text"])
        # fallback: stringify content
        return str(content)
    except Exception:
        return ""


def _extract_bedrock_converse_usage(response: Dict[str, Any]) -> Dict[str, int]:
    """
    Bedrock Converse response commonly includes:
      response["usage"]["inputTokens"], ["outputTokens"], ["totalTokens"]
    """
    usage = response.get("usage") or {}
    def _to_int(x: Any) -> int:
        try:
            return int(x)
        except Exception:
            return 0

    return {
        "input": _to_int(usage.get("inputTokens")),
        "output": _to_int(usage.get("outputTokens")),
        "total": _to_int(usage.get("totalTokens")),
    }


# -----------------------------
# Convenience class (optional)
# -----------------------------

@dataclass(frozen=True)
class BedrockRuntimeWithLangfuse:
    """
    Cleaner OO wrapper if you prefer not to pass region/client each call.
    """
    region_name: Optional[str] = None
    client: Optional[BaseClient] = None

    def converse(
        self,
        *,
        modelId: str,
        messages: List[Dict[str, Any]],
        inferenceConfig: Optional[Dict[str, Any]] = None,
        additionalModelRequestFields: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return wrapped_bedrock_converse(
            modelId=modelId,
            messages=messages,
            inferenceConfig=inferenceConfig,
            additionalModelRequestFields=additionalModelRequestFields,
            region_name=self.region_name,
            bedrock_runtime_client=self.client,
            **kwargs,
        )