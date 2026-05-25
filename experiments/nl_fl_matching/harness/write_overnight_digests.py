"""Write synthetic digest.json files for the 4 overnight Aristotle results that
didn't get one written by the rescue script (since the rescue processes died
when /tmp was wiped). Source data: aristotle download + task status.
"""
import json
import re
import uuid
from pathlib import Path

RUNS = Path("/gscratch/amath/simku22/TheoremSearch/experiments/nl_fl_matching/harness/runs")
RP = RUNS / "returned_proofs"


def count_sorries(text: str) -> int:
    # Count instances of `sorry` as a token (not inside identifiers)
    return len(re.findall(r"\bsorry\b", text))


def make_digest(
    *,
    candidate_label: str,
    arm: str,
    project_id: str,
    task_status_raw: str,
    final_lean_path,
    trajectory_jsonl_path,
    extra_note: str = "",
) -> dict:
    source = final_lean_path.read_text()
    sorry_final = count_sorries(source)
    # All four targets sent with exactly 1 sorry (the bare `:= by sorry`)
    sorry_init = 1

    # Map terminal Aristotle status to our status enum
    status_map = {
        "COMPLETE_WITH_ERRORS": "partial",
        "OUT_OF_BUDGET": "out_of_budget",
        "CANCELED": "canceled",
    }
    status = status_map.get(task_status_raw, "unknown")

    return {
        "run_id": str(uuid.uuid4()),
        "candidate_label": candidate_label,
        "arm": arm,
        "status": status,
        "summary": (
            f"Recovered from orphan project {project_id}; final task status "
            f"{task_status_raw}. {extra_note}".strip()
        ),
        "sorry_count_initial": sorry_init,
        "sorry_count_final": sorry_final,
        "aristotle_submits": 1,  # we know there was at least 1 submit; exact count lost
        "aristotle_asks": 0,
        "subagent_turns": None,
        "wall_time_s": None,
        "rescue_poll_time_s": None,
        "trajectory_jsonl_path": trajectory_jsonl_path,
        "subagent_model": "(recovered: no live subagent; digest synthesized from final state)",
        "final_lean_source": source,
        "rescue": True,
        "aristotle_project_id": project_id,
        "final_task_status_raw": task_status_raw,
    }


def main() -> None:
    overnight = [
        dict(
            candidate_label="A_martingale_iff_classDL",
            arm="no_graph",
            project_id="ddb6ae7f-4934-47f7-a730-afa2722214c4",
            task_status_raw="OUT_OF_BUDGET",
            final_lean_path=RP / "A_martingale__no_graph__attempt1__ddb6ae7f.lean",
            trajectory_jsonl_path=None,
            extra_note=(
                "Aristotle proved 3 helper lemmas (stopped_process_eq_of_lt, "
                "ae_tendsto_stopped_of_localizing, ClassDL.integrable) before "
                "hitting budget; both iff directions remain as sorry."
            ),
        ),
        dict(
            candidate_label="A_martingale_iff_classDL",
            arm="with_graph",
            project_id="a8214974-c549-428c-8e64-6823e26795b9",
            task_status_raw="COMPLETE_WITH_ERRORS",
            final_lean_path=RP / "A_martingale__with_graph__attempt1__a8214974.lean",
            trajectory_jsonl_path=None,
            extra_note=(
                "Aristotle added a detailed English 'Proof sketch' docstring covering "
                "both directions of the iff but did not write any Lean — the body is "
                "still `:= by sorry`."
            ),
        ),
        dict(
            candidate_label="A_martingale_iff_classDL",
            arm="with_graph",
            project_id="a51b745a-0def-4785-a00f-58ad5b5512a2",
            task_status_raw="COMPLETE_WITH_ERRORS",
            final_lean_path=RP / "A_martingale__with_graph__attempt2__a51b745a.lean",
            trajectory_jsonl_path=None,
            extra_note=(
                "Second attempt (rescue restart). Aristotle structured the iff as a "
                "composition of two helper lemmas (martingale_to_classDL, "
                "classDL_to_martingale), each left as sorry. Premise pack slightly "
                "pruned/reordered from the input."
            ),
        ),
        dict(
            candidate_label="B_submartingale_iff_classDL",
            arm="with_graph",
            project_id="5cd4e9d0-cfa9-42f6-84b1-88edb13eec3f",
            task_status_raw="COMPLETE_WITH_ERRORS",
            final_lean_path=RP / "B_submartingale__with_graph__attempt1__5cd4e9d0.lean",
            trajectory_jsonl_path=None,
            extra_note=(
                "Aristotle built a 4-helper-lemma scaffold "
                "(stoppedProcess_eq_of_lt_tau, integrable_of_classDL, "
                "condexp_mono_*, progMeasurable_*, uniformIntegrable_*) plus iff via "
                "composition. stoppedProcess_eq_of_lt_tau is fully closed with "
                "simp+aesop. integrable_of_classDL contains literal `exact?` calls "
                "(unfinished search trace), which is why the build reports errors."
            ),
        ),
    ]

    written = []
    for spec in overnight:
        d = make_digest(**spec)
        # Filename mirrors rescue.py's pattern: <label>__<arm>__<timestamp>_rescue.digest.json
        fname = f"{spec['candidate_label']}__{spec['arm']}__recovered_{spec['project_id'][:8]}.digest.json"
        out = RUNS / fname
        out.write_text(json.dumps(d, indent=2, ensure_ascii=False))
        written.append((out, d["status"], d["sorry_count_final"]))

    print("Wrote:")
    for path, st, sf in written:
        print(f"  {path.name}  status={st}  sorry_final={sf}")


if __name__ == "__main__":
    main()
