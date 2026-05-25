"""Trajectory analyzer for the prover-comparison harness.

Reads every JSONL trajectory under runs/ plus its sibling
*.digest.json (or _rescue.digest.json), and computes:

  per (candidate, arm):
    * status, sorry delta, wall time, turn count, tokens
    * tool-call breakdown (how many read/typecheck/submit/ask/report)
    * premise utilization (only meaningful for with_graph arm — count
      of premise-pack decl names that appear in the returned proof
      body)

  aggregate:
    * pass rate × arm
    * mean turns / submits / wall_time × arm
    * paired per-candidate no_graph vs with_graph delta

Output: a Markdown summary table on stdout + JSON dump for downstream
plotting at data/trajectory_analysis.json.

Run from repo root:
    python3 -m experiments.nl_fl_matching.harness.analyze_trajectories
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

RUNS_DIR = REPO_ROOT / "experiments/nl_fl_matching/harness/runs"
HARNESS_DIR = REPO_ROOT / "experiments/nl_fl_matching/harness"
DATA_OUT = REPO_ROOT / "experiments/nl_fl_matching/data/trajectory_analysis.json"

# Map candidate label → directory containing no_graph.lean / with_graph.lean
CANDIDATES = {
    "A_martingale_iff_classDL":    HARNESS_DIR / "A_martingale_iff_classDL",
    "B_submartingale_iff_classDL": HARNESS_DIR / "B_submartingale_iff_classDL",
    "F_eta_def":                   HARNESS_DIR / "F_eta_def",
}

_PREMISE_RE = re.compile(r"example\s*:=\s*@([\w.]+)")


def parse_premise_pack(with_graph_path: Path) -> list[str]:
    """Pull the decl names from `example := @<decl>` lines in a with_graph.lean."""
    if not with_graph_path.exists():
        return []
    return _PREMISE_RE.findall(with_graph_path.read_text())


def load_trajectory(jsonl_path: Path) -> list[dict]:
    rows = []
    with jsonl_path.open() as fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def tool_call_breakdown(traj: list[dict]) -> Counter:
    counts: Counter = Counter()
    for r in traj:
        if r.get("kind") == "tool_call":
            counts[r.get("tool", "?")] += 1
    return counts


def find_digest(jsonl_path: Path) -> dict | None:
    """Look for a paired digest file (subagent or rescue)."""
    for suffix in (".digest.json", "_rescue.digest.json"):
        candidate = jsonl_path.with_name(jsonl_path.stem + suffix)
        if candidate.exists():
            return json.loads(candidate.read_text())
    # also try sibling rescue files without matching prefix
    for sibling in jsonl_path.parent.glob("*_rescue.digest.json"):
        d = json.loads(sibling.read_text())
        if d.get("trajectory_jsonl_path") == str(jsonl_path):
            return d
    return None


def count_premise_uses(proof_source: str, premises: list[str]) -> dict:
    """Count how many premises appear by name in the returned proof.

    Heuristic: substring match on the bare decl name (last dot-separated
    component) AND on the fully-qualified name. Counts each premise as
    used iff either form appears at least once outside the original
    `example := @<decl>` line.
    """
    if not proof_source or not premises:
        return {"used_count": 0, "used": [], "premise_pack_size": len(premises)}
    # Strip the original Premises section so we don't double-count.
    stripped = re.sub(r"section Premises.*?end Premises", "",
                      proof_source, flags=re.DOTALL)
    used = []
    for p in premises:
        bare = p.split(".")[-1]
        if p in stripped or re.search(rf"\b{re.escape(bare)}\b", stripped):
            used.append(p)
    return {"used_count": len(used), "used": used, "premise_pack_size": len(premises)}


def collect_runs() -> list[dict]:
    out = []
    for jsonl in sorted(RUNS_DIR.glob("*.jsonl")):
        digest = find_digest(jsonl)
        if not digest:
            # subagent crashed before writing digest; treat as in-flight
            continue
        traj = load_trajectory(jsonl)
        tools = tool_call_breakdown(traj)

        cand = digest.get("candidate_label")
        arm = digest.get("arm")
        with_graph_path = (CANDIDATES.get(cand, Path()) / "with_graph.lean") if cand else Path()
        premises = parse_premise_pack(with_graph_path)
        usage = count_premise_uses(digest.get("final_lean_source", ""), premises)

        out.append({
            "trajectory_path": str(jsonl),
            "candidate": cand,
            "arm": arm,
            "is_rescue": digest.get("rescue", False),
            "status": digest.get("status"),
            "sorry_initial": digest.get("sorry_count_initial"),
            "sorry_final": digest.get("sorry_count_final"),
            "wall_time_s": digest.get("wall_time_s"),
            "subagent_turns": digest.get("subagent_turns"),
            "aristotle_submits": digest.get("aristotle_submits"),
            "aristotle_asks": digest.get("aristotle_asks"),
            "subagent_tokens_in": digest.get("subagent_tokens_in"),
            "subagent_tokens_out": digest.get("subagent_tokens_out"),
            "tool_calls": dict(tools),
            "premise_utilization": usage,
        })
    return out


def render_markdown(runs: list[dict]) -> str:
    if not runs:
        return "(no trajectories with digests yet)"
    lines = []
    lines.append("# Trajectory analysis\n")
    lines.append(f"_{len(runs)} runs analyzed_\n")

    # Per-run table
    lines.append("## Per-run")
    lines.append("| candidate | arm | rescue | status | sorry Δ | turns | submits | wall (s) | tokens (in/out) | premises used |")
    lines.append("|---|---|:-:|---|---|---:|---:|---:|---|---|")
    for r in runs:
        sorry_d = f"{r['sorry_initial']}→{r['sorry_final']}"
        toks = f"{r['subagent_tokens_in']}/{r['subagent_tokens_out']}"
        pu = r["premise_utilization"]
        prem = f"{pu['used_count']}/{pu['premise_pack_size']}" if pu['premise_pack_size'] else "n/a"
        rescue = "✓" if r["is_rescue"] else ""
        wall = f"{r['wall_time_s']:.0f}" if r['wall_time_s'] else "?"
        lines.append(f"| {r['candidate']} | {r['arm']} | {rescue} | {r['status']} | {sorry_d} | "
                     f"{r['subagent_turns']} | {r['aristotle_submits']} | {wall} | {toks} | {prem} |")
    lines.append("")

    # Tool-call breakdown
    lines.append("## Tool-call breakdown (per run)")
    lines.append("| candidate | arm | read | typecheck | submit | ask | report |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for r in runs:
        t = r["tool_calls"]
        lines.append(f"| {r['candidate']} | {r['arm']} | "
                     f"{t.get('read_target_file', 0)} | "
                     f"{t.get('lean_typecheck', 0)} | "
                     f"{t.get('aristotle_submit', 0)} | "
                     f"{t.get('aristotle_ask', 0)} | "
                     f"{t.get('report_final', 0)} |")
    lines.append("")

    # Aggregate by arm
    by_arm = defaultdict(list)
    for r in runs:
        by_arm[r["arm"]].append(r)

    lines.append("## Aggregate by arm")
    lines.append("| arm | n | proved | partial | failed/error | mean turns | mean submits | mean wall (s) |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for arm, rs in sorted(by_arm.items()):
        n = len(rs)
        proved = sum(1 for x in rs if x["status"] == "proved")
        partial = sum(1 for x in rs if x["status"] == "partial")
        failed = sum(1 for x in rs if x["status"] in ("failed", "error", "budget_exhausted"))
        def m(key):
            xs = [x[key] for x in rs if x[key] is not None]
            return sum(xs) / len(xs) if xs else 0
        lines.append(f"| {arm} | {n} | {proved} | {partial} | {failed} | "
                     f"{m('subagent_turns'):.1f} | {m('aristotle_submits'):.1f} | "
                     f"{m('wall_time_s'):.0f} |")
    lines.append("")

    # Paired per-candidate delta
    by_cand = defaultdict(dict)
    for r in runs:
        by_cand[r["candidate"]][r["arm"]] = r
    lines.append("## Paired per-candidate delta (no_graph → with_graph)")
    lines.append("| candidate | no_graph status | with_graph status | sorry Δ ng | sorry Δ wg | turn Δ |")
    lines.append("|---|---|---|---|---|---:|")
    for cand, arms in sorted(by_cand.items()):
        ng = arms.get("no_graph", {})
        wg = arms.get("with_graph", {})
        def sd(r):
            if not r: return "?"
            return f"{r.get('sorry_initial','?')}→{r.get('sorry_final','?')}"
        turn_delta = ""
        if ng.get("subagent_turns") is not None and wg.get("subagent_turns") is not None:
            turn_delta = str(wg["subagent_turns"] - ng["subagent_turns"])
        lines.append(f"| {cand} | {ng.get('status','-')} | {wg.get('status','-')} | "
                     f"{sd(ng)} | {sd(wg)} | {turn_delta} |")
    return "\n".join(lines)


def main():
    runs = collect_runs()
    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    DATA_OUT.write_text(json.dumps(runs, default=str, indent=2))
    print(render_markdown(runs))
    print(f"\n_JSON dump: {DATA_OUT}_")


if __name__ == "__main__":
    main()
