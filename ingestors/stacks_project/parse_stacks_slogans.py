import os
import csv
import re

STACKS_ROOT = "external/stacks-project"
OUTPUT_CSV = "stacks_label_slogans.csv"

THEOREM_ENVS = {
    "theorem",
    "lemma",
    "proposition",
    "corollary"
}

begin_env_re = re.compile(r"\\begin\{(\w+)\}")
end_env_re   = re.compile(r"\\end\{(\w+)\}")
label_re     = re.compile(r"\\label\{([^}]+)\}")

def strip_comments(line):
    return re.sub(r"(?<!\\)%.*", "", line)

def parse_file(path):
    rows = []

    current_env = None
    current_label = None

    inside_slogan = False
    slogan_lines = []

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = strip_comments(raw).strip()

            # Start of environment
            m = begin_env_re.search(line)
            if m and m.group(1) in THEOREM_ENVS:
                current_env = m.group(1)
                current_label = None
                slogan_lines = []
                inside_slogan = False
                continue

            if current_env is None:
                continue

            # Label (first one wins)
            if current_label is None:
                m = label_re.search(line)
                if m:
                    current_label = m.group(1)

            # Slogan capture
            if "\\begin{slogan}" in line:
                inside_slogan = True
                slogan_lines = []
                continue

            if "\\end{slogan}" in line:
                inside_slogan = False
                continue

            if inside_slogan:
                slogan_lines.append(line)

            # End of environment → emit
            m = end_env_re.search(line)
            if m and m.group(1) == current_env:
                if current_label and slogan_lines:
                    slogan = " ".join(s.strip() for s in slogan_lines)
                    rows.append((current_label, slogan))
                current_env = None

    return rows

def main():
    pairs = []

    for root, _, files in os.walk(STACKS_ROOT):
        for f in files:
            if f in {"preamble.tex", "macros.tex"}:
                continue
            if f.endswith(".tex"):
                pairs.extend(parse_file(os.path.join(root, f)))

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(["label", "slogan"])
        writer.writerows(pairs)

    print(f"Extracted {len(pairs)} label–slogan pairs")

if __name__ == "__main__":
    main()
