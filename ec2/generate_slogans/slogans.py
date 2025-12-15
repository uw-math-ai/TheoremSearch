import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import dotenv
import pandas as pd
from tqdm import tqdm

from cost import format_USD
from typing import Dict

from langfuse.langchain import CallbackHandler
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

def _deepseek_cost_usd(usage: dict) -> float:
    """
    Approx DeepSeek pricing (cache miss) in USD:
    input:  $0.27 / 1M tokens
    output: $1.10 / 1M tokens
    """
    prompt_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0) or 0
    completion_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0) or 0

    cost_input = prompt_tokens * 0.27 / 1_000_000
    cost_output = completion_tokens * 1.10 / 1_000_000
    return cost_input + cost_output


def _generate_theorem_slogan(
    instructions: str,
    theorem_context: dict,
    model: str,  # kept for API compatibility, not used
    i: int,
) -> tuple[int, str | None, float]:
    theorem_context = theorem_context.copy()
    if "theorem_id" in theorem_context:
        del theorem_context["theorem_id"]

    cost = 0.0

    langfuse_handler = CallbackHandler()

    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=os.getenv("deepseek_key"),
        base_url="https://api.deepseek.com",
    )

    prompt_tmpl = ChatPromptTemplate.from_messages(
        [
            ("system", "{instructions}"),
            ("user", "{theorem_context_json}"),
        ]
    )

    chain = prompt_tmpl | llm

    try:
        theorem_context_str = json.dumps(theorem_context)

        res = chain.invoke(
            {
                "instructions": instructions,
                "theorem_context_json": theorem_context_str,
            },
            config={
                "callbacks": [langfuse_handler],
                "metadata": {
                    "generation_name": "theorem_slogan",
                    "theorem_index": i,
                },
            },
        )

        slogan = res.content
        usage = res.response_metadata.get("token_usage", {}) if hasattr(res, "response_metadata") else {}
        cost = _deepseek_cost_usd(usage)

        return i, slogan, cost
    except Exception:
        return i, None, cost

def generate_theorem_slogans(
    theorem_contexts: list[dict],
    instructions: str,
    model: str,
    max_workers: int = 16,
    max_retries: int = 4,
) -> list[str | None]:
    slogans: list[str | None] = [None for _ in theorem_contexts]
    retries = 0

    total_cost = 0.0
    slogans_generated = 0

    with ThreadPoolExecutor(max_workers) as ex, tqdm(total=len(theorem_contexts)) as pbar:
        while None in slogans:
            if retries > max_retries:
                break

            futs = {
                ex.submit(
                    _generate_theorem_slogan,
                    instructions,
                    theorem_context,
                    model,
                    i,
                )
                for i, theorem_context in enumerate(theorem_contexts)
                if slogans[i] is None
            }

            for fut in as_completed(futs):
                idx, slogan, cost = fut.result()
                slogans[idx] = slogan
                total_cost += cost

                if slogan is not None:
                    pbar.update(1)
                    slogans_generated += 1

                pbar.set_postfix(
                    {
                        "cost": format_USD(total_cost),
                        "avg": format_USD(
                            0 if slogans_generated == 0 else total_cost / slogans_generated
                        ),
                    }
                )

            retries += 1

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


