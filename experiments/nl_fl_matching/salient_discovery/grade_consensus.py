"""Airtight 2-rater Opus consensus grading of candidate Mathlib<->arXiv edges.

NOT a single model rating: each candidate gets TWO independent blind Opus grades
(neutral rubric, same as the validation run). If they AGREE -> confirmed. If they
DISAGREE -> a third Opus tie-break, majority of 3 decides; a genuine 3-way split
-> AMBIGUOUS (abstain, we do NOT claim it). This controls false positives (a fluke
must fool two independent graders) AND false negatives (rejections are double-graded
too), and abstains honestly on the irreducibly hard.

Runs on klone via `claude -p --model opus` (Max OAuth, NOT API key; needs login).
stdin=DEVNULL (see run_band_filter). Checkpoint/resume by (query_sid,cand_sid).
RDS untouched — reads only the local/gscratch matches CSV.

  cd /gscratch/amath/simku22/TheoremSearch
  export HTTPS_PROXY=http://klone-dip1:3128 HTTP_PROXY=http://klone-dip1:3128
  export PYTHONPATH=$PWD:$PWD/rds
  /gscratch/amath/simku22/salient_venv/bin/python \
    experiments/nl_fl_matching/salient_discovery/grade_consensus.py \
    --csv /gscratch/amath/simku22/salient_matches_full.csv \
    --out /gscratch/amath/simku22/consensus_ge90.jsonl \
    --bands 0.95-1.0,0.90-0.95 --workers 5
"""
from __future__ import annotations
import argparse, csv, json, os, re, subprocess, threading, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

CLAUDE = os.path.expanduser("~/.local/bin/claude")
LABELS = ["exact", "inexact", "wrong", "unjudgeable"]
EDGE = {"exact", "inexact"}

PROMPT = """You are verifying a candidate link between a FORMAL Lean declaration and an INFORMAL mathematical statement (from an arXiv paper or a formalization blueprint). Decide whether they state the SAME mathematical result.

Judge the actual MATHEMATICAL CONTENT — the hypotheses, the conclusion, the object being defined — NOT surface word overlap. Lexically similar slogans about DIFFERENT theorems are common in this data; do not be fooled by shared vocabulary.

FORMAL (Lean):
  decl_name: {formal_decl}
  slogan: {formal_slogan}
  Lean signature/source:
{formal_body}

INFORMAL ({source} {arxiv_id} {paper_title}; ref {informal_ref}):
  slogan: {informal_slogan}
  statement (LaTeX):
{informal_body}

Choose exactly ONE label using this operational test:
  exact   - They state the SAME proposition. A mathematician would cite the Lean decl as THE formalization of this exact informal statement with NO caveat. Any difference is only notation/formalization syntax (symbols vs words, an iff spelled _iff, a definition unfolded, argument order).
  inexact - They concern the SAME underlying result but are NOT identical: one is a generalization, a special case, ONE direction of an iff, or a sub-component of the other; linking them needs a caveat or a small step.
  wrong   - They state DIFFERENT theorems or define DIFFERENT objects, even if in the same area or sharing words. Whenever the core object or the claim differs, this is wrong.
  unjudgeable - One side's text is genuinely missing or too vague to determine its content. Use ONLY then.

Decision rules:
- SELF-CONSISTENCY GUARD: `exact` allows ZERO caveat. If your own one-sentence reason names ANY difference in a hypothesis, premise, or conclusion (wording like "differs", "but the formal has", "special case", "only one direction", "sub-component", "generalization", "stronger/weaker"), you MUST label `inexact` or `wrong` — NEVER `exact`.
- Do NOT default to `inexact` when unsure. If the two state genuinely different theorems, label `wrong`.
- `inexact` requires that it is provably the SAME result up to a generalization/specialization/one-direction caveat — not merely the same topic.
- `unjudgeable` is not a hedge; use it only for missing/empty text.

Output ONLY a JSON object, no prose and no tool use:
{{"label":"exact|inexact|wrong|unjudgeable","reason":"one short sentence naming the key matching content, or the specific mismatch"}}
"""


def _extract(out: str):
    out = (out or "").strip()
    if out.startswith("```"):
        out = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", out).strip()
    for cand in (out, ):
        try:
            return json.loads(cand)
        except Exception:
            pass
    m = re.search(r"\{[^{}]*\"label\"[^{}]*\}", out, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    m = re.search(r"\{.*\}", out, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def rate(row: dict, model: str, max_retries: int = 5):
    src = (row.get("informal_source") or "").strip()
    source = "arXiv" if "arx" in src.lower() else (src or "informal source")
    prompt = PROMPT.format(
        formal_decl=row["formal_decl"], formal_slogan=row["formal_slogan"][:400],
        formal_body=(row["formal_body"][:1100] or "(none)"),
        source=source, arxiv_id=row["arxiv_id"], paper_title=(row["paper_title"] or "")[:120],
        informal_ref=row["informal_ref"], informal_slogan=row["informal_slogan"][:400],
        informal_body=(row["informal_body"][:1100] or "(none)"),
    )
    for a in range(max_retries):
        try:
            p = subprocess.run([CLAUDE, "-p", prompt, "--model", model, "--no-session-persistence"],
                               capture_output=True, text=True, timeout=300,
                               stdin=subprocess.DEVNULL)
            j = _extract(p.stdout)
            if j and j.get("label") in LABELS:
                return {"label": j["label"], "reason": str(j.get("reason", ""))[:200]}
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        time.sleep(min(90, 5 * (2 ** a)))
    return None   # exhausted -> SKIP whole candidate (retried next run)


def resolve(labels):
    """labels: list of 2 or 3 fine labels. Returns (final_label, edge_bool_or_None, status)."""
    a, b = labels[0], labels[1]
    if a == b:
        return a, (a in EDGE), "confirmed"
    if len(labels) >= 3:
        cnt = Counter(labels)
        top, n = cnt.most_common(1)[0]
        if n >= 2:
            return top, (top in EDGE), "tiebroken"
        # 3-way split on fine label: fall back to EDGE-collapse majority
        edge_votes = sum(1 for L in labels if L in EDGE)
        if edge_votes >= 2:
            return None, True, "edge_ambiguous"   # agree it's an edge, unsure exact/inexact
        if edge_votes <= 1:
            return None, False, "notedge_ambiguous"
    return None, None, "ambiguous"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bands", default="0.95-1.0,0.90-0.95",
                    help="comma list of bands to include")
    ap.add_argument("--cls", default="mathlib", help="'mathlib', 'project', or 'all'")
    ap.add_argument("--any-source", action="store_true",
                    help="include non-arXiv informal sources (blueprint); default arXiv-only")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--raters", type=int, default=2)
    ap.add_argument("--no-tiebreak", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    bands = set(args.bands.split(","))
    csv.field_size_limit(10_000_000)
    rows = [r for r in csv.DictReader(open(args.csv))
            if r["band"] in bands
            and (args.cls == "all" or r["cls"] == args.cls)
            and (args.any_source or "arx" in (r["informal_source"] or "").lower())]
    rows.sort(key=lambda r: -float(r["sim"]))   # high-sim first (deliver best edges early)
    print(f"scope: bands={sorted(bands)} cls={args.cls} any_source={args.any_source}: {len(rows):,} candidates", flush=True)

    def key(r):
        return f'{r["query_sid"]}|{r["cand_sid"]}'

    done = set()
    if os.path.exists(args.out):
        for l in open(args.out):
            l = l.strip()
            if l:
                try:
                    done.add(json.loads(l)["key"])
                except Exception:
                    pass
    todo = [r for r in rows if key(r) not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"done: {len(done):,}  todo: {len(todo):,}  (model={args.model} workers={args.workers} raters={args.raters})", flush=True)
    if not todo:
        print("nothing to do."); return

    lock = threading.Lock()
    st = {"n": 0, "fail": 0, "status": Counter(), "edge": Counter(), "t0": time.time()}
    fh = open(args.out, "a")

    def work(r):
        labels, reasons = [], []
        for _ in range(args.raters):
            res = rate(r, args.model)
            if res is None:
                with lock:
                    st["fail"] += 1
                return
            labels.append(res["label"]); reasons.append(res["reason"])
        if labels[0] != labels[1] and not args.no_tiebreak:
            res = rate(r, args.model)        # tie-break
            if res is None:
                with lock:
                    st["fail"] += 1
                return
            labels.append(res["label"]); reasons.append(res["reason"])
        final, edge, status = resolve(labels)
        rec = {"key": key(r), "query_sid": r["query_sid"], "cand_sid": r["cand_sid"],
               "sim": r["sim"], "band": r["band"], "formal_decl": r["formal_decl"],
               "arxiv_id": r["arxiv_id"], "labels": labels, "reasons": reasons,
               "final": final, "edge": edge, "status": status}
        with lock:
            fh.write(json.dumps(rec) + "\n"); fh.flush()
            st["n"] += 1; st["status"][status] += 1
            st["edge"][edge] += 1
            if st["n"] % 25 == 0:
                el = time.time() - st["t0"]
                print(f"  {st['n']}/{len(todo)}  {el:.0f}s ({el/st['n']:.1f}s/cand)  "
                      f"fail={st['fail']}  status={dict(st['status'])}  edge={dict(st['edge'])}", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, todo))
    fh.close()
    print(f"DONE: {st['n']} graded. status={dict(st['status'])}  edge={dict(st['edge'])}  fail={st['fail']}", flush=True)


if __name__ == "__main__":
    main()
