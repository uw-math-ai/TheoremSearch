"""One subagent run for a single (candidate, arm) pair.

The subagent is a Claude model in a tool-use loop. It gets the target
Lean file, a brownian-motion (or other project) worktree, and a budget
of N aristotle submissions + M asks. Its job: drive the proof to
status=proved (or report partial/failed/budget_exhausted).

Every turn — every Claude message, every tool call, every tool result —
is appended to a JSONL trajectory file. That trajectory IS the data the
paper will use to compare arms.

Usage:
    python -m experiments.nl_fl_matching.harness.subagent \
        --candidate-label A_martingale_iff_classDL \
        --arm with_graph \
        --target /path/to/with_graph.lean \
        --project-dir /tmp/simku22/repos/brownian-motion \
        --trajectory /path/to/run.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

# Load TheoremSearch/.env so BEDROCK_API_KEY / AWS_REGION pick up the
# repo-managed values without the operator having to `export` them.
try:
    import dotenv
    dotenv.load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass  # dotenv is optional; falls back to plain os.environ

# Use AWS Bedrock as the Claude backend (no separate ANTHROPIC_API_KEY
# required; BEDROCK_API_KEY in .env is sufficient).
try:
    from anthropic import AnthropicBedrock
except ImportError as e:
    print("ERROR: anthropic SDK not installed. `pip install --user anthropic`.",
          file=sys.stderr)
    raise

from experiments.nl_fl_matching.harness import tools  # noqa: E402


# === budget ===

MAX_ARISTOTLE_SUBMITS = 2
MAX_ARISTOTLE_ASKS = 1
MAX_TURNS = 25            # claude turns; safety cap to prevent loops

# Bedrock model ID. Override via SUBAGENT_MODEL env var if you want a
# different snapshot. Bedrock IDs of the form
# us.anthropic.claude-<family>-<rev>-<date>-v1:0 (the `us.` prefix
# enables cross-region inference profiles).
SUBAGENT_MODEL = os.environ.get(
    "SUBAGENT_MODEL",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",  # latest Sonnet on Bedrock as of 2026-05; bump when 4.6/4.7 land
)
MAX_TOKENS_PER_TURN = 4000

# === tool schema for the model ===

TOOL_DEFS = [
    {
        "name": "read_target_file",
        "description": "Read the current contents of the target Lean file you're trying to prove. Returns full source plus a count of remaining `sorry` occurrences.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "write_target_file",
        "description": "Overwrite the target Lean file with new contents. Use to add a hint comment, restructure the proof skeleton, or insert `have` lemmas before the main goal. The target file is the one Aristotle submissions act on.",
        "input_schema": {
            "type": "object",
            "properties": {"content": {"type": "string", "description": "Full new file contents."}},
            "required": ["content"],
        },
    },
    {
        "name": "lean_typecheck",
        "description": "Run `lake env lean` on the target file to confirm it well-types. Run this before submitting to Aristotle if you've modified the file — saves an Aristotle call on a syntactic error.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "aristotle_submit",
        "description": "Submit the project_dir (containing the target file) to Aristotle. The CLI blocks until completion (--wait). Returns project_id, status (PROVED/PARTIAL/FAILED/ERROR), and stdout. Aristotle attempts every `sorry` in the file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Natural-language instructions to Aristotle (e.g. 'Fill the sorry in the target theorem. Use the provided premise pack if available.')."}
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "aristotle_ask",
        "description": "Send a follow-up instruction to an in-progress aristotle project (the one most recently submitted). Useful for nudging the prover after a partial result.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "report_final",
        "description": "Terminate the run with a final status and one-paragraph summary. Required as the last tool call. status must be one of: proved, partial, failed, error, budget_exhausted.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["proved", "partial", "failed", "error", "budget_exhausted"]},
                "summary": {"type": "string"},
                "final_lean_source": {"type": "string", "description": "The full contents of the target file at the end of the run (or 'unchanged' if you didn't modify it)."},
            },
            "required": ["status", "summary"],
        },
    },
]


# === trajectory writer ===

class Trajectory:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = path.open("a")
        self.turn = 0

    def log(self, kind: str, **kwargs):
        row = {"turn": self.turn, "ts": datetime.now(timezone.utc).isoformat(),
               "kind": kind, **kwargs}
        self.fh.write(json.dumps(row, default=str) + "\n")
        self.fh.flush()

    def next_turn(self):
        self.turn += 1

    def close(self):
        self.fh.close()


# === system prompt ===

SYSTEM_PROMPT = """You are an automated theorem-proving agent driving the Aristotle Lean prover.

Your job: take a Lean 4 file containing one or more `sorry` placeholders and use the aristotle CLI (exposed as tools) to fill them in.

Process:
1. Use `read_target_file` to see what you're working with.
2. Optionally use `lean_typecheck` to confirm the file elaborates before submitting (saves an Aristotle call on a syntactic error).
3. Use `aristotle_submit` with a clear prompt — Aristotle attempts every sorry in the file. Aristotle returns status PROVED / PARTIAL / FAILED / ERROR.
4. If not proved: you may use `aristotle_ask` to send a follow-up hint to the same project, OR modify the file (e.g. add an explanatory comment, restructure the goal as `have` lemmas) and submit again.
5. Always end with `report_final`. Pick status carefully:
   - `proved` if Aristotle returned PROVED and no sorries remain
   - `partial` if some but not all sorries closed
   - `failed` if Aristotle reported FAILED / could not prove
   - `error` if a tool failed irrecoverably
   - `budget_exhausted` if you hit the call cap

Budget (HARD limits):
- {MAX_SUBMITS} aristotle_submit calls
- {MAX_ASKS} aristotle_ask calls
- {MAX_TURNS} total conversation turns

Be concise. Reason briefly, act, observe, repeat. Don't re-read the target file unless it changed.

The two arms of this experiment differ only in what premise hints the file contains. Your job is to drive each one fairly using the same protocol — don't try to "help" the with_graph arm by manually researching extra lemmas, and don't sandbag no_graph. Just prove what's in front of you.
"""

# === main agent loop ===

def run(*, candidate_label: str, arm: str, target_path: Path,
        project_dir: Path, trajectory_path: Path) -> dict:
    """Run one subagent loop. Returns a digest dict suitable for prover_run."""
    traj = Trajectory(trajectory_path)
    run_id = str(uuid.uuid4())
    t0 = time.time()
    traj.log("run_start", run_id=run_id, candidate_label=candidate_label,
             arm=arm, target_path=str(target_path), project_dir=str(project_dir),
             subagent_model=SUBAGENT_MODEL,
             budget={"max_submits": MAX_ARISTOTLE_SUBMITS,
                     "max_asks": MAX_ARISTOTLE_ASKS,
                     "max_turns": MAX_TURNS})

    initial_source = target_path.read_text()
    sorry_count_initial = initial_source.count("sorry")

    # AnthropicBedrock uses the standard boto3 credential chain
    # (AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY from .env work for our
    # account; the BEDROCK_API_KEY bearer token does NOT — verified
    # empirically 2026-05-24). Explicitly clear any stale bearer token
    # so it doesn't shadow SigV4.
    os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
    client = AnthropicBedrock(aws_region=os.environ.get("AWS_REGION", "us-west-2"))

    system_prompt = SYSTEM_PROMPT.format(
        MAX_SUBMITS=MAX_ARISTOTLE_SUBMITS,
        MAX_ASKS=MAX_ARISTOTLE_ASKS,
        MAX_TURNS=MAX_TURNS,
    )
    user_msg = (
        f"You are working on candidate `{candidate_label}`, arm `{arm}`.\n"
        f"Target file: `{target_path}`\n"
        f"Project directory (pass this to aristotle): `{project_dir}`\n"
        f"Initial sorry count: {sorry_count_initial}\n\n"
        "Start by reading the target file."
    )
    messages = [{"role": "user", "content": user_msg}]
    traj.log("user_msg", content=user_msg)

    # State we track across the loop.
    submits, asks, turns = 0, 0, 0
    tokens_in, tokens_out = 0, 0
    final_digest = None
    last_project_id = None

    while turns < MAX_TURNS:
        turns += 1
        traj.next_turn()
        try:
            resp = client.messages.create(
                model=SUBAGENT_MODEL,
                max_tokens=MAX_TOKENS_PER_TURN,
                system=system_prompt,
                tools=TOOL_DEFS,
                messages=messages,
            )
        except Exception as e:
            traj.log("api_error", error=str(e))
            final_digest = {"status": "error", "summary": f"API error: {e}"}
            break

        tokens_in += resp.usage.input_tokens
        tokens_out += resp.usage.output_tokens
        traj.log("assistant_msg", stop_reason=resp.stop_reason,
                 usage={"in": resp.usage.input_tokens, "out": resp.usage.output_tokens},
                 content=[
                     {"type": b.type, **({"text": b.text} if b.type == "text"
                                         else {"name": b.name, "input": b.input}
                                              if b.type == "tool_use" else {})}
                     for b in resp.content
                 ])

        # Append the assistant turn to messages history.
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "end_turn":
            traj.log("end_turn_without_report")
            final_digest = {"status": "error", "summary": "agent ended turn without calling report_final"}
            break

        # Execute tool calls. Multiple tool_use blocks possible per turn.
        tool_results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            name = block.name
            inputs = block.input or {}
            traj.log("tool_call", tool=name, input=inputs, tool_use_id=block.id)

            if name == "read_target_file":
                result = tools.read_target_file(str(target_path))
            elif name == "write_target_file":
                result = tools.write_target_file(str(target_path), inputs.get("content", ""))
            elif name == "lean_typecheck":
                # file_relpath relative to project_dir
                try:
                    rel = target_path.relative_to(project_dir)
                except ValueError:
                    rel = target_path  # fallback; lean will error
                result = tools.lean_typecheck(str(project_dir), str(rel))
            elif name == "aristotle_submit":
                if submits >= MAX_ARISTOTLE_SUBMITS:
                    result = {"ok": False, "error": "budget_exhausted: max submits reached"}
                else:
                    submits += 1
                    dest = trajectory_path.parent / f"submit_{submits}_destination"
                    result = tools.aristotle_submit(
                        prompt=inputs.get("prompt", "Fill the sorry."),
                        project_dir=str(project_dir),
                        destination=str(dest),
                        wait=True,
                    )
                    if result.get("project_id"):
                        last_project_id = result["project_id"]
            elif name == "aristotle_ask":
                if asks >= MAX_ARISTOTLE_ASKS:
                    result = {"ok": False, "error": "budget_exhausted: max asks reached"}
                elif not last_project_id:
                    result = {"ok": False, "error": "no project_id from prior submit"}
                else:
                    asks += 1
                    result = tools.aristotle_ask(last_project_id, inputs.get("prompt", ""))
            elif name == "report_final":
                final_digest = {
                    "status": inputs.get("status", "error"),
                    "summary": inputs.get("summary", ""),
                    "final_lean_source": inputs.get("final_lean_source", "unchanged"),
                }
                result = {"ok": True, "reported": True}
            else:
                result = {"ok": False, "error": f"unknown tool: {name}"}

            traj.log("tool_result", tool=name, tool_use_id=block.id, result=result)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, default=str)[:4000],
            })

        if final_digest is not None:
            break

        # Append user message containing tool results.
        messages.append({"role": "user", "content": tool_results})

    else:
        # while-else: hit turn cap without reporting
        final_digest = {"status": "budget_exhausted", "summary": f"hit MAX_TURNS={MAX_TURNS} without final report"}

    # The staged target file is what we submitted — Aristotle writes the
    # filled-in source to the per-submit destination dir, NOT back to
    # the staged file. Look for the returned counterpart of the staged
    # file in the most recent submit destination; fall back to the
    # staged file only if nothing was returned.
    final_source = ""
    final_source_origin = "staged"  # for trajectory transparency
    for n in range(submits, 0, -1):
        dest = trajectory_path.parent / f"submit_{n}_destination"
        if not dest.exists():
            continue
        for candidate_file in dest.rglob(target_path.name):
            final_source = candidate_file.read_text()
            final_source_origin = str(candidate_file)
            break
        if final_source:
            break
    if not final_source and target_path.exists():
        final_source = target_path.read_text()
    sorry_count_final = final_source.count("sorry")
    wall = time.time() - t0
    traj.log("final_source_resolution", origin=final_source_origin,
             sorry_count_initial=sorry_count_initial,
             sorry_count_final=sorry_count_final)
    digest = {
        "run_id": run_id,
        "candidate_label": candidate_label,
        "arm": arm,
        "status": final_digest.get("status", "error"),
        "summary": final_digest.get("summary", ""),
        "sorry_count_initial": sorry_count_initial,
        "sorry_count_final": sorry_count_final,
        "aristotle_submits": submits,
        "aristotle_asks": asks,
        "subagent_turns": turns,
        "wall_time_s": wall,
        "subagent_tokens_in": tokens_in,
        "subagent_tokens_out": tokens_out,
        "trajectory_jsonl_path": str(trajectory_path),
        "subagent_model": SUBAGENT_MODEL,
        "final_lean_source": final_source[:8000],
    }
    traj.log("run_end", **{k: v for k, v in digest.items() if k != "final_lean_source"})
    traj.close()
    return digest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--candidate-label", required=True)
    p.add_argument("--arm", required=True, choices=["no_graph", "with_graph"])
    p.add_argument("--target", required=True, type=Path)
    p.add_argument("--project-dir", required=True, type=Path)
    p.add_argument("--trajectory", required=True, type=Path)
    args = p.parse_args()

    digest = run(candidate_label=args.candidate_label, arm=args.arm,
                 target_path=args.target, project_dir=args.project_dir,
                 trajectory_path=args.trajectory)
    print(json.dumps(digest, default=str, indent=2))


if __name__ == "__main__":
    main()
