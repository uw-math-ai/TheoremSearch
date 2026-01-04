import os
import json
import time
import boto3
from typing import Dict, Tuple
from botocore.client import BaseClient
from .enums import Mode
from .types import SloganPrompt
from .models import MODELS
from .langfuse_bedrock import wrapped_bedrock_converse  # NEW

brc: BaseClient | None = None
def _get_brc() -> BaseClient:
    global brc

    if brc is None:
        brc = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION"))

    return brc

def generate_slogan(
    model_name: str,
    prompt: SloganPrompt,
    theorem_id: str,
    context: Dict,
    retries: int,
    use_langfuse: bool = True,
    mode: Mode = Mode.PRODUCTION
) -> Tuple[str | None, float]:
    """
    Generates a slogan for one theorem.

    Parameters
    ----------
        model_name : str
            Name of model from `models.py`
        prompt : SloganPrompt
            The prompt to give the LLM
        theorem_id : str
            The ID of the theorem
        context : Dict
            Dict containing all relevant theorem contexts
        retries : int
            Number of retries for slogan generation
        use_langfuse : bool, optional
            Whether to use Langfuse. By default, True
        mode : Mode, optional
            Mode to run `generate_slogan` in. By default, PRODUCTION

    Returns
    -------
        slogan : str | None
            The generated slogan. None if the LLM believes the theorem contexts cannot be used to
            form a slogan
        cost : float
            The cost in USD of slogan generation attempt
    """
    model = MODELS[model_name]

    brc = _get_brc()

    messages = [
        {"role": "user", "content": prompt["instructions"]},
        # TODO: Figure out how to prompt LLM to not generate a slogan if absolutely impossible
        #{"role": "user", "content": "Treat malformed TeX as placeholders. If this context becomes empty, return 'CORRUPTED TeX:' followed by a short one-sentence reason."},
        {"role": "user", "content": json.dumps(context)}
    ]
    payload = {
        "messages": messages,
        "max_tokens": prompt["max_tokens"],
        "temperature": prompt["temperature"]
    }

    tries_left = retries + 1

    while tries_left > 0:
        tries_left -= 1

        try:
            if use_langfuse:
                # NOTE: Bedrock Converse uses "content blocks" (e.g. [{"text": "..."}])
                # so we adapt your existing messages into the Converse format here.
                converse_messages = [
                    {"role": "user", "content": [{"text": prompt["instructions"]}]},
                    # TODO: Figure out how to prompt LLM to not generate a slogan if absolutely impossible
                    # {"role": "user", "content": [{"text": "Treat malformed TeX as placeholders. If this context becomes empty, return 'CORRUPTED TeX:' followed by a short one-sentence reason."}]},
                    {"role": "user", "content": [{"text": json.dumps(context)}]},
                ]

                body = wrapped_bedrock_converse(
                    modelId=model["id"],
                    messages=converse_messages,
                    inferenceConfig={
                        "maxTokens": prompt["max_tokens"],
                        "temperature": prompt["temperature"],
                    },
                    region_name=os.getenv("AWS_REGION"),
                    bedrock_runtime_client=brc
                )

                slogan: str = body["output"]["message"]["content"][0]["text"]
                if slogan:
                    slogan = slogan.strip()
                else:
                    raise RuntimeError(f"slogan = `{slogan}`")

                usage = body.get("usage") or {}
                input_tokens = int(usage.get("inputTokens", 0))
                output_tokens = int(usage.get("outputTokens", 0))

            else:
                res = brc.invoke_model(
                    modelId=model["id"],
                    body=json.dumps(payload),
                    accept="application/json",
                    contentType="application/json"
                )

                body = json.loads(res["body"].read())

                slogan: str = body["choices"][0]["message"]["content"]
                if slogan:
                    slogan = slogan.strip()
                else:
                    raise RuntimeError(f"slogan = `{slogan}`")

                # Compute cost
                headers = res["ResponseMetadata"]["HTTPHeaders"]
                input_tokens = int(headers["x-amzn-bedrock-input-token-count"])
                output_tokens = int(headers["x-amzn-bedrock-output-token-count"])

        except Exception as e:
            if mode == Mode.DEBUGGING:
                print(f"[DEBUG] {theorem_id}: {e}")

            time.sleep(2**(retries - tries_left))
            continue

        cost = (
            input_tokens * model["input_token_cost"]
            + output_tokens * model["output_token_cost"]
        )

        if slogan.startswith("CORRUPTED TeX:"):
            # This branch will never be reach right now since we aren't worrying about corrupted TeX
            if mode == Mode.DEBUGGING:
                bad_theorem_reason = slogan.removeprefix("CORRUPTED TeX:").strip()

                print(f"[DEBUG] {theorem_id}: CORRUPTED TeX, {bad_theorem_reason} ({context['theorem.body']})")
            return None, cost
        else:
            return slogan, cost

    raise RuntimeError(f"Slogan generation failed on all {retries} retries")