"""Generate two natural-language queries per theorem via the OpenAI API.

For each picked theorem, produce:
  - "precise": one-sentence informal restatement, ~15-30 words
  - "vague":   high-level conceptual query, ~5-15 words (topic + setting only)

Output: ../data/queries.json — list of {paper, label, type, target_title, mode, query}
        with 2 entries per theorem (one per mode).

Reads OPENAI_API_KEY from the repo .env.

Note: in the original run, paraphrasing was done via the Codex CLI tool. This
script reproduces the same behavior using the OpenAI API directly. Per-batch
calls to keep prompt size small. Set OPENAI_MODEL to override (default
"gpt-5.2").
"""
import json, os, sys, time, urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
PICKS = os.path.join(ROOT, "picks.json")
QUERIES = os.path.join(ROOT, "queries.json")
BATCH_SIZE = 25
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.2")


def load_env():
    """Load OPENAI_API_KEY from <repo>/.env if not already set."""
    if os.environ.get("OPENAI_API_KEY"):
        return
    repo_env = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env")
    if os.path.exists(repo_env):
        for line in open(repo_env):
            if line.strip().startswith("OPENAI_API_KEY="):
                os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip()


PROMPT = """You are paraphrasing theorem statements from research math papers. \
For each theorem in the JSON array, produce TWO search-engine queries:

1. **precise**: A concise informal restatement of the theorem (one sentence, ~15-30 words). \
Strip LaTeX commands but keep mathematical concepts. Re-express the math in clean prose. \
Do NOT just copy phrases verbatim — actually paraphrase. Keep core technical terms.

2. **vague**: A high-level conceptual query someone might Google when looking for this kind \
of result, ~5-15 words. Should NOT contain the precise mathematical statement — just the \
topic/setting. Like "criterion for X under Y" or "vanishing of cohomology of Z".

Use `paper_title` only as context for the area; do NOT include the paper title in the queries.

Return ONLY a JSON array of {"id":"...","precise":"...","vague":"..."} in the same length \
and order as the input. No commentary, no markdown fences."""


def call_openai(batch):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        sys.exit("OPENAI_API_KEY not set (and not found in repo .env).")
    payload = {
        "model": MODEL,
        "input": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": json.dumps(batch)},
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    resp = json.load(urllib.request.urlopen(req, timeout=120))
    # Responses API: pluck the first output_text
    text = ""
    for out in resp.get("output", []):
        for c in out.get("content", []):
            if c.get("type") in ("output_text", "text"):
                text += c.get("text", "")
    text = text.strip()
    # Strip accidental fences
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def main():
    load_env()
    picks = json.load(open(PICKS))
    print(f"Paraphrasing {len(picks)} theorems in batches of {BATCH_SIZE}", flush=True)

    all_para: list[dict] = []
    for bi in range(0, len(picks), BATCH_SIZE):
        chunk = picks[bi:bi + BATCH_SIZE]
        payload = [
            {"id": f"b{bi // BATCH_SIZE}_t{j}",
             "paper_title": item['title'],
             "type": item['type'],
             "body": item['body']}
            for j, item in enumerate(chunk)
        ]
        try:
            out = call_openai(payload)
        except Exception as e:
            print(f"  batch {bi // BATCH_SIZE} failed: {e}", file=sys.stderr)
            time.sleep(5); continue
        if len(out) != len(chunk):
            print(f"  batch {bi // BATCH_SIZE}: got {len(out)}, expected {len(chunk)}", file=sys.stderr)
        all_para.extend(out)
        print(f"  batch {bi // BATCH_SIZE + 1}/{(len(picks) + BATCH_SIZE - 1) // BATCH_SIZE}: +{len(out)}", flush=True)

    queries: list[dict] = []
    for pick, para in zip(picks, all_para):
        for mode in ("precise", "vague"):
            queries.append({
                "paper": pick['paper'], "label": pick['label'], "type": pick['type'],
                "target_title": pick['title'],
                "mode": mode, "query": para[mode],
            })
    with open(QUERIES, "w") as f:
        json.dump(queries, f, indent=1)
    print(f"DONE: {len(queries)} queries → {QUERIES}", flush=True)


if __name__ == "__main__":
    main()
