"""Sample papers from confirmed overlap set, download arXiv source, extract
theorem environments, and pick 4 random non-main theorems per paper.

Pipeline:
  confirmed.json → sample.json (60 random papers, seed=42)
                 → src/<arxiv_id>/*.tex (e-print tarballs unpacked)
                 → envs.json (theorem environments per paper)
                 → picks.json (4 non-main theorems per paper, capped at 50 papers)

"Non-main" = drop the first 2 environments per paper (typically headline
results) and pick 4 random from the rest. Uses seed=42 for reproducibility.
"""
import json, urllib.request, os, re, glob, tarfile, gzip, io, sys, time, random

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
SRC_DIR = os.path.join(ROOT, "src")
CONFIRMED = os.path.join(ROOT, "confirmed.json")
SAMPLE = os.path.join(ROOT, "sample.json")
ENVS = os.path.join(ROOT, "envs.json")
PICKS = os.path.join(ROOT, "picks.json")

ENV_PAT = re.compile(
    r"\\begin\{(theorem|thm|lemma|lem|proposition|prop|corollary|cor)\*?\}(.*?)\\end\{\1\*?\}",
    re.DOTALL | re.IGNORECASE,
)
LABEL_PAT = re.compile(r"\\label\{([^}]+)\}")

SAMPLE_SIZE = 60      # over-sample to allow extraction failures
TARGET_PAPERS = 50    # final size after extraction
PICKS_PER_PAPER = 4
MIN_ENVS_FOR_PICK = 8 # need enough non-main envs to pick 4


def fetch_source(aid: str) -> str | None:
    out_dir = os.path.join(SRC_DIR, aid)
    if os.path.exists(out_dir) and glob.glob(f"{out_dir}/*.tex"):
        return out_dir
    os.makedirs(out_dir, exist_ok=True)
    try:
        data = urllib.request.urlopen(f"https://arxiv.org/e-print/{aid}", timeout=60).read()
    except Exception as e:
        print(f"  fetch err {aid}: {e}", file=sys.stderr); return None
    # Try tar.gz
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
        for m in tf.getmembers():
            if m.isfile() and m.name.endswith('.tex'):
                f = tf.extractfile(m)
                if f:
                    open(f"{out_dir}/{os.path.basename(m.name)}", "wb").write(f.read())
        tf.close()
        return out_dir
    except Exception:
        pass
    # Try plain gzip (single .tex)
    try:
        txt = gzip.decompress(data).decode('utf-8', 'ignore')
        open(f"{out_dir}/main.tex", "w").write(txt)
        return out_dir
    except Exception:
        pass
    print(f"  unknown fmt {aid}", file=sys.stderr); return None


def extract_envs(src_dir: str) -> list[list]:
    items: list[list] = []
    for path in sorted(glob.glob(f"{src_dir}/*.tex")):
        try:
            txt = open(path, encoding='utf-8', errors='ignore').read()
        except Exception:
            continue
        txt = re.sub(r"(?<!\\)%.*", "", txt)  # strip line comments
        for m in ENV_PAT.finditer(txt):
            env = m.group(1).lower()
            body = m.group(2).strip()
            lbl_m = LABEL_PAT.search(body)
            lbl = lbl_m.group(1) if lbl_m else None
            body = re.sub(r"^\s*\[[^\]]*\]\s*", "", body)
            body = re.sub(r"\\label\{[^}]+\}", "", body)
            body = re.sub(r"\s+", " ", body).strip()
            if 60 < len(body) < 1500:
                items.append([env, lbl, body])
    return items


def main():
    confirmed = json.load(open(CONFIRMED))
    random.seed(42)

    # 1. Sample
    items = sorted(confirmed.items())
    sample = dict(random.sample(items, SAMPLE_SIZE))
    with open(SAMPLE, "w") as f:
        json.dump(sample, f, indent=1)
    print(f"Sampled {len(sample)} papers (seed=42)", flush=True)

    # 2. Download + extract
    os.makedirs(SRC_DIR, exist_ok=True)
    all_envs: dict[str, list] = {}
    for i, (aid, meta) in enumerate(sample.items()):
        src = fetch_source(aid)
        if not src:
            time.sleep(2); continue
        envs = extract_envs(src)
        if envs:
            all_envs[aid] = envs
        print(f"  {i+1}/{len(sample)}: {aid} -> {len(envs)} envs", flush=True)
        time.sleep(0.5)
    with open(ENVS, "w") as f:
        json.dump(all_envs, f)
    print(f"Extracted: {len(all_envs)} papers, total {sum(len(v) for v in all_envs.values())} envs", flush=True)

    # 3. Pick 4 non-main per paper, cap at TARGET_PAPERS papers
    picks: list[dict] = []
    papers_used: list[str] = []
    for aid in sorted(all_envs.keys()):
        items = all_envs[aid]
        if len(items) < MIN_ENVS_FOR_PICK:
            continue
        seen = set(); pool = []
        for it in items[2:]:  # skip headline results
            if it[2] in seen:
                continue
            seen.add(it[2])
            pool.append(it)
        if len(pool) < PICKS_PER_PAPER:
            continue
        chosen = random.sample(pool, PICKS_PER_PAPER)
        for c in chosen:
            picks.append({
                "paper": aid,
                "title": sample[aid]['title'],
                "journal": sample[aid].get('journal', '?'),
                "year": sample[aid].get('year', '?'),
                "type": c[0], "label": c[1], "body": c[2],
            })
        papers_used.append(aid)
        if len(papers_used) >= TARGET_PAPERS:
            break

    with open(PICKS, "w") as f:
        json.dump(picks, f, indent=1)
    print(f"DONE: picked {len(picks)} theorems from {len(papers_used)} papers → {PICKS}", flush=True)


if __name__ == "__main__":
    main()
