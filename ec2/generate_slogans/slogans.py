from concurrent.futures import ThreadPoolExecutor, as_completed
import dotenv
import pandas as pd
from typing import Dict, List
from .cost import format_USD
import json
import time
from langfuse import Langfuse
from botocore.client import BaseClient
from .models import MODELS

def _generate_theorem_slogan(
    brc: BaseClient,
    langfuse: Langfuse,
    prompt: Dict,
    theorem_context: Dict,
    model_name: str,
    i: int,
    verbose: bool
) -> tuple[int, str, float]:
    model = MODELS[model_name]

    cost = 0
    start_time = time.time()

    prompt_id = prompt["prompt_id"]
    instructions = prompt["instructions"]
    temperature = prompt["temperature"]

    theorem_context = theorem_context.copy()
    theorem_id = theorem_context.pop("theorem_id", None)

    with langfuse.start_as_current_observation(
        as_type="span",
        name="generate_theorem_slogan",
        input={
            "instructions": instructions,
            "theorem_context": theorem_context,
        },
        metadata={
            "theorem_id": theorem_id,
            "prompt_id": prompt_id,
            "model": model_name
        },
    ) as root_span:
        try:
            theorem_context_str = json.dumps(theorem_context)

            messages = [
                {"role": "user", "content": instructions},
                {"role": "user", "content": theorem_context_str},
            ]
            payload = {"messages": messages, "max_tokens": 1024, "temperature": temperature}

            with langfuse.start_as_current_observation(
                as_type="generation",
                name="aws_bedrock_completion",
                model=model_name,
                input=messages,
                model_parameters={"temperature": temperature, "max_tokens": 1024},
            ) as gen:
                res = brc.invoke_model(
                    modelId=model["model_id"],
                    body=json.dumps(payload),
                    accept="application/json",
                    contentType="application/json",
                )

                body = json.loads(res["body"].read())
                headers = res["ResponseMetadata"]["HTTPHeaders"]

                slogan = body["choices"][0]["message"]["content"]
                if slogan is not None:
                    slogan = slogan.strip()

                input_tokens = int(headers["x-amzn-bedrock-input-token-count"])
                output_tokens = int(headers["x-amzn-bedrock-output-token-count"])
                cost = (
                    input_tokens * model["input_token_cost"]
                    + output_tokens * model["output_token_cost"]
                )

                gen.update(
                    output=slogan,
                    usage_details={
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                    },
                    metadata={
                        "cost_usd": cost,
                        "latency_s": time.time() - start_time,
                    },
                )

            root_span.update(output={"slogan": slogan})
            return i, slogan, cost

        except Exception as e:
            if verbose:
                print(f"[LLM ERROR] {e}")

            root_span.update(metadata={"error": str(e)})
            return i, None, 0

def generate_theorem_slogans(
    brc: BaseClient, 
    langfuse: Langfuse,
    theorem_contexts: List[dict],
    prompt: Dict,
    model_name: str,
    pbar,
    max_workers: int,
    max_retries: int,
    verbose: bool
) -> list[str | None]:
    slogans = [None for _ in theorem_contexts]
    retries = 0

    total_cost = 0
    slogans_generated = 0

    with ThreadPoolExecutor(max_workers) as ex:
        while None in slogans:
            if retries > max_retries:
                if verbose:
                    print(f"[MAX RETRIES REACHED] Used all {max_retries}")

                break

            futs = {
                ex.submit(
                    _generate_theorem_slogan, 
                    brc, 
                    langfuse, 
                    prompt, 
                    theorem_context, 
                    model_name, 
                    i, 
                    verbose
                )
                for i, theorem_context in enumerate(theorem_contexts)
                if slogans[i] is None
            }
            for fut in as_completed(futs):
                res = fut.result()
                slogans[res[0]] = res[1]
                total_cost += res[2]

                if res[1] is not None:
                    pbar.update(1)
                    slogans_generated += 1
                
                pbar.set_postfix({
                    "cost": format_USD(total_cost), 
                    "avg": format_USD(0 if slogans_generated == 0 else total_cost / slogans_generated)
                })

            retries += 1

    langfuse.flush()

    return slogans

if __name__ == "__main__":
    dotenv.load_dotenv()
    prompt = [
    "You summarize math theorems based on theorem_body.",
    "You are summarizing the LAST theorem mentioned in theorem_body.",
    "You may use the first section of the paper as context, but do NOT mention the paper or the text explicitly.",
    "Summaries are accurate and <= 4 sentences.",
    "Summaries must be plain ASCII text (no Unicode).",
    "Avoid LaTeX and math symbols. Use words instead of symbols when possible.",
    "Include key identifiers (names, objects, conditions) that aid retrieval.",
    "Your output must be a single paragraph of continuous prose.",
    "OUTPUT CONSTRAINTS:",
    "- Output ONLY the summary paragraph.",
    "- Do NOT include any introductory phrases, explanations, or meta-commentary.",
    "- Do NOT say what you are doing (e.g. 'I will...', 'Here is...', 'Based on the text...').",
    "- Do NOT refer to 'the theorem', 'the proposition', 'the lemma', 'this result', or 'this statement'.",
    "- Do NOT use phrases like 'Based on the provided text', 'here is an accurate summary', etc.",
    "If you are unsure, still produce your best guess of the summary, but FOLLOW ALL THE OUTPUT CONSTRAINTS.",
    "Your response will be automatically post-processed. Any text that is not part of the summary content will be treated as an error.",
    "Therefore, do not include any extra words, labels, headings, or explanations."
    ]
    df = pd.read_csv("validation_set.csv", header=0, index_col=0, dtype={"paper_id": str})
    df = df[df["body"].notnull()]
    queries = list(zip(df['paper_id'], df["body"], df["theorem"]))

    for (i,item) in enumerate(queries):

        try:

            thm = {
                "first_section": "",   
                "theorem_body": item[1]
            }
            with open(rf"parsed_papers\{item[0]}.json", 'r') as f:
                x = json.load(f)
                thm["first_section"] = x["first_section"]

            prompt = " ".join(prompt)
            a, b, c = _generate_theorem_slogan(
                prompt,
                thm,
                "deepseek/deepseek-chat",
                1
            )

            print(item[2])
            print("="*50)
            print(b)
            print("="*50)
            print(c)

        except:
            print(f"Failure for {item[0]}, {item[2]}")
            continue


