#!/usr/bin/env python3
"""
pdf_textbook_ingestor.py

Drop PDF textbooks into the input/ folder, run this script, and get
structured JSON entries for MathCopilot.

Workflow:
    1. Put your PDF(s) in the input/ folder
    2. Run: python pdf_textbook_ingestor.py
    3. Output appears in data/sources/{book-name}/

Uses marker-pdf for OCR (outputs Markdown with LaTeX math).

Dependencies:
    pip install marker-pdf

Options:
    python pdf_textbook_ingestor.py                     # process all PDFs in input/
    python pdf_textbook_ingestor.py --pages 0-20        # only these pages (for testing)
    python pdf_textbook_ingestor.py --nougat-only       # just OCR, skip JSON parsing
    python pdf_textbook_ingestor.py --from-mmd SLUG     # skip OCR, re-parse existing .md
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Folder layout
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent
INPUT_DIR = REPO_ROOT / "input"
DATA_SOURCES_DIR = REPO_ROOT / "data" / "sources"


# ---------------------------------------------------------------------------
# Marker OCR
# ---------------------------------------------------------------------------

def run_marker(pdf_path: Path, output_dir: Path, pages: Optional[str] = None) -> Path:
    """
    Run marker-pdf on a PDF. Returns path to the output .md file.
    marker outputs Markdown with LaTeX math in $ and $$ delimiters.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # marker_single [OPTIONS] FPATH
    cmd = [
        "marker_single",
        "--output_format", "markdown",
        "--output_dir", str(output_dir),
        str(pdf_path),
    ]

    if pages:
        # marker uses --page_range
        cmd.insert(-1, "--page_range")
        cmd.insert(-1, pages)

    print(f"  [marker] Running OCR...")
    print(f"  [marker] Command: {' '.join(cmd)}")
    start = time.time()

    result = subprocess.run(cmd, capture_output=True, text=True)

    elapsed = time.time() - start
    print(f"  [marker] Done in {elapsed:.1f}s")

    if result.returncode != 0:
        print(f"  [marker] stderr: {result.stderr[:500]}", file=sys.stderr)

    # Find the .md file marker produced
    md_file = find_md_output(output_dir, pdf_path.stem)

    if md_file is None:
        if result.returncode != 0:
            raise RuntimeError(
                f"marker failed (exit code {result.returncode}).\n"
                f"  stderr: {result.stderr[:300]}\n"
                f"  Try running manually: marker_single --output_dir \"{output_dir}\" \"{pdf_path}\""
            )
        raise FileNotFoundError(
            f"No .md file found in {output_dir} after marker ran.\n"
            f"  Check: dir \"{output_dir}\" /s"
        )

    print(f"  [marker] Output: {md_file.name} ({md_file.stat().st_size / 1024:.1f} KB)")
    return md_file


def find_md_output(output_dir: Path, stem: str) -> Optional[Path]:
    """Find the markdown file marker produced, checking multiple possible locations."""
    # Check output_dir/{stem}/{stem}.md
    candidate = output_dir / stem / f"{stem}.md"
    if candidate.exists() and candidate.stat().st_size > 0:
        return candidate

    # Check output_dir/{stem}.md
    candidate = output_dir / f"{stem}.md"
    if candidate.exists() and candidate.stat().st_size > 0:
        return candidate

    # Glob for any .md file
    for md in output_dir.rglob("*.md"):
        if md.stat().st_size > 0:
            return md

    return None


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

ENV_PATTERN = re.compile(
    r"^\*\*("
    r"Theorem|Definition|Lemma|Proposition|Corollary|Example|Remark|Conjecture|Axiom|Property"
    r")\s*([\d.]+)?\*\*"
    r"(?:\s*\(([^)]+)\))?"
    r"\.?\s*",
    re.IGNORECASE
)

# Also match non-bold variants: "Theorem 3.4.14." or "Definition 2.1.1 (Name)."
ENV_PATTERN_ALT = re.compile(
    r"^("
    r"Theorem|Definition|Lemma|Proposition|Corollary|Example|Remark|Conjecture|Axiom|Property"
    r")\s+([\d.]+)"
    r"(?:\s*\(([^)]+)\))?"
    r"\.?\s*",
    re.IGNORECASE
)

CHAPTER_PATTERN = re.compile(
    r"^#{1,2}\s*(?:Chapter\s+)?(\d+)\s*[.:]?\s*(.*)",
    re.IGNORECASE
)

SECTION_PATTERN = re.compile(
    r"^#{2,4}\s*(\d+\.\d+)\s*[.:]?\s*(.*)"
)

PROOF_START = re.compile(r"^\*?\*?Proof\.?\*?\*?\.?\s*", re.IGNORECASE)
PROOF_END_MARKERS = ["∎", "□", "Q.E.D.", "qed", "\\blacksquare", "\\square"]


def parse_markdown(md_path: Path, source: str) -> list[dict]:
    """Parse a marker-pdf markdown file into ProofWiki-format theorem dicts."""
    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    theorems: list[dict] = []
    current_chapter = None
    current_chapter_title = None
    current_section = None
    current_section_title = None

    current_entry: Optional[dict] = None
    collecting_proof = False
    proof_lines: list[str] = []
    body_lines: list[str] = []

    def flush_entry():
        nonlocal current_entry, body_lines, proof_lines, collecting_proof
        if current_entry is None:
            return
        current_entry["body"] = clean_body("\n".join(body_lines))
        if proof_lines:
            current_entry["proof"] = clean_body("\n".join(proof_lines))
        if len(current_entry["body"].strip()) > 20:
            theorems.append(current_entry)
        current_entry = None
        body_lines = []
        proof_lines = []
        collecting_proof = False

    for i, line in enumerate(lines):
        stripped = line.rstrip()

        # Section header (check BEFORE chapter)
        sec_match = SECTION_PATTERN.match(stripped)
        if sec_match:
            flush_entry()
            current_section = sec_match.group(1)
            current_section_title = sec_match.group(2).strip() or None
            continue

        # Chapter header
        ch_match = CHAPTER_PATTERN.match(stripped)
        if ch_match and not stripped.startswith("###"):
            flush_entry()
            current_chapter = int(ch_match.group(1))
            current_chapter_title = ch_match.group(2).strip() or None
            current_section = None
            current_section_title = None
            continue

        # Theorem-like environment (bold)
        env_match = ENV_PATTERN.match(stripped)
        # Fallback: non-bold variant
        if not env_match:
            env_match = ENV_PATTERN_ALT.match(stripped)

        if env_match:
            flush_entry()
            env_type = env_match.group(1).lower()
            env_number = env_match.group(2)
            env_name = env_match.group(3)

            label = env_match.group(1)
            if env_number:
                label += f" {env_number}"
            theorem_name = label
            if env_name:
                theorem_name += f" ({env_name})"

            context_parts = []
            if current_chapter_title:
                context_parts.append(f"Ch{current_chapter} {current_chapter_title}")
            if current_section_title:
                context_parts.append(f"{current_section} {current_section_title}")
            context_parts.append(theorem_name)

            current_entry = {
                "theorem_name": " > ".join(context_parts),
                "type": env_type,
                "body": "",
                "url": None,
                "proof": None,
            }

            remainder = stripped[env_match.end():]
            if remainder.strip():
                body_lines.append(remainder)
            continue

        # Proof start
        if PROOF_START.match(stripped):
            if current_entry is not None:
                collecting_proof = True
                remainder = PROOF_START.sub("", stripped)
                if remainder.strip():
                    proof_lines.append(remainder)
                continue

        # Proof end
        if collecting_proof and any(m in stripped for m in PROOF_END_MARKERS):
            proof_lines.append(stripped)
            collecting_proof = False
            continue

        # Accumulate content
        if current_entry is not None:
            if collecting_proof:
                proof_lines.append(stripped)
            else:
                body_lines.append(stripped)

    flush_entry()
    return theorems


def clean_body(text: str) -> str:
    text = text.replace("\\(", "$").replace("\\)", "$")
    text = text.replace("\\[", "$$").replace("\\]", "$$")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > 3000:
        text = text[:3000] + "..."
    return text


# ---------------------------------------------------------------------------
# Save output
# ---------------------------------------------------------------------------

def save_output(theorems: list[dict], source: str, output_path: Path):
    data = {
        "source": source,
        "theorems": theorems,
    }
    tmp = str(output_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, str(output_path))


# ---------------------------------------------------------------------------
# Process one PDF
# ---------------------------------------------------------------------------

def process_pdf(
    pdf_path: Path,
    source: Optional[str] = None,
    slug: Optional[str] = None,
    pages: Optional[str] = None,
    ocr_only: bool = False,
):
    slug = slug or re.sub(r"[^a-z0-9]+", "-", pdf_path.stem.lower()).strip("-")
    source = source or pdf_path.stem.replace("_", " ").replace("-", " ")

    output_dir = DATA_SOURCES_DIR / slug
    output_dir.mkdir(parents=True, exist_ok=True)

    marker_out = output_dir / "marker_output"
    json_path = output_dir / f"{slug}.json"

    print(f"\n{'='*60}")
    print(f"Processing: {pdf_path.name}")
    print(f"Output:     data/sources/{slug}/")
    print(f"{'='*60}")

    # Step 1: OCR
    md_path = run_marker(pdf_path, marker_out, pages=pages)

    if ocr_only:
        print(f"  [done] OCR-only mode. Markdown at: {md_path}")
        return

    # Step 2: Parse
    print(f"  [parse] Extracting theorems...")
    theorems = parse_markdown(md_path, source)

    # Step 3: Save
    save_output(theorems, source, json_path)

    # Summary
    type_counts: dict[str, int] = {}
    for t in theorems:
        entry_type = t.get("type", "other")
        type_counts[entry_type] = type_counts.get(entry_type, 0) + 1

    print(f"  [done] {len(theorems)} entries:")
    for t, c in sorted(type_counts.items()):
        print(f"         {t}: {c}")
    print(f"  [done] Saved to: {json_path}")


# ---------------------------------------------------------------------------
# Re-parse existing markdown
# ---------------------------------------------------------------------------

def reparse_md(slug: str, source: Optional[str] = None):
    output_dir = DATA_SOURCES_DIR / slug
    marker_dir = output_dir / "marker_output"

    md_file = find_md_output(marker_dir, slug) if marker_dir.exists() else None
    if md_file is None:
        print(f"[error] No .md files found in data/sources/{slug}/marker_output/")
        sys.exit(1)

    source = source or slug.replace("-", " ")
    json_path = output_dir / f"{slug}.json"

    print(f"Re-parsing: {md_file.name}")
    theorems = parse_markdown(md_file, source)
    save_output(theorems, source, json_path)
    print(f"  [done] {len(theorems)} entries -> {json_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Drop PDFs in input/, run this script, get structured JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  1. Put PDFs in the input/ folder
  2. python pdf_textbook_ingestor.py
  3. Output in data/sources/{book-name}/

Options:
  --pages 0-20       Only process these pages (for testing)
  --ocr-only         Just run marker, skip JSON parsing
  --from-md SLUG     Re-parse existing markdown without re-running OCR
  --source "..."     Override source citation
  --slug NAME        Override output folder name
        """
    )

    parser.add_argument("--pages", default=None, help="Page range (e.g. '0-20')")
    parser.add_argument("--ocr-only", action="store_true", help="Only run OCR")
    parser.add_argument("--from-md", default=None, metavar="SLUG",
                        help="Re-parse existing markdown for this slug")
    parser.add_argument("--source", default=None, help="Source citation override")
    parser.add_argument("--slug", default=None, help="Output folder name override")

    args = parser.parse_args()

    # Re-parse mode
    if args.from_md:
        reparse_md(args.from_md, source=args.source)
        return

    # Create input/ if it doesn't exist
    INPUT_DIR.mkdir(exist_ok=True)

    # Find PDFs
    pdfs = sorted(INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in input/")
        print(f"  Put your PDF files in: {INPUT_DIR}")
        print(f"  Then run this script again.")
        sys.exit(0)

    print(f"Found {len(pdfs)} PDF(s) in input/:")
    for p in pdfs:
        print(f"  - {p.name}")

    # Process each
    for pdf_path in pdfs:
        process_pdf(
            pdf_path=pdf_path,
            source=args.source,
            slug=args.slug if len(pdfs) == 1 else None,
            pages=args.pages,
            ocr_only=args.ocr_only,
        )

    print(f"\nAll done!")


if __name__ == "__main__":
    main()