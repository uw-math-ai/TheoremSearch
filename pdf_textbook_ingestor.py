#!/usr/bin/env python3
"""
pdf_textbook_ingestor.py

Drop PDF textbooks into the input/ folder, run this script, and get
structured JSON entries for MathCopilot — same format as proofwiki.json.

Workflow:
    1. Put your PDF(s) in the input/ folder
    2. Run: python pdf_textbook_ingestor.py
    3. Output appears in data/sources/{book-name}/

Uses marker-pdf for OCR (outputs Markdown with LaTeX math).

Dependencies:
    pip install marker-pdf

Options:
    python pdf_textbook_ingestor.py                  # process all PDFs in input/
    python pdf_textbook_ingestor.py --pages 0-20     # only these pages (for testing)
    python pdf_textbook_ingestor.py --reparse SLUG   # skip OCR, re-parse cached .md
    python pdf_textbook_ingestor.py --source "Artin Algebra, 2nd ed."
    python pdf_textbook_ingestor.py --slug artin-algebra
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Folder layout
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent
INPUT_DIR = REPO_ROOT / "input"
DATA_SOURCES_DIR = REPO_ROOT / "data" / "sources"


# ---------------------------------------------------------------------------
# Marker OCR  (lazy import so the script fails fast with a clear message)
# ---------------------------------------------------------------------------

# Matches actual theorem headers: "Theorem 1.2.3" or "Lemma 2.4" at the start
# of a line — NOT in-text references like "by Theorem 1.2".
THEOREM_HEADER = re.compile(
    r"^(Theorem|Lemma|Proposition|Corollary|Definition|Remark|Example|Conjecture|Axiom)"
    r"\s+\d+[\d.]*",
    re.IGNORECASE | re.MULTILINE,
)

# How many pages before/after a theorem page to also include (catches proofs
# that spill onto the next page)
PAGE_BUFFER = 1


def find_theorem_pages(pdf_path: Path) -> list[int]:
    """
    Fast pymupdf scan: returns 0-indexed page numbers that contain theorem
    keywords (plus a buffer of surrounding pages).  Takes < 1 second.
    """
    try:
        import fitz
    except ImportError:
        print("[!] pymupdf is required for fast scanning.  Install: pip install pymupdf")
        sys.exit(1)

    doc = fitz.open(str(pdf_path))
    total = len(doc)
    hit_pages: set[int] = set()

    for i in range(total):
        text = doc[i].get_text("text")
        if THEOREM_HEADER.search(text):
            # add the page and its neighbours
            for offset in range(-PAGE_BUFFER, PAGE_BUFFER + 1):
                p = i + offset
                if 0 <= p < total:
                    hit_pages.add(p)

    doc.close()
    return sorted(hit_pages)


def pages_to_ranges(pages: list[int]) -> list[str]:
    """
    Collapse a sorted list of page numbers into compact ranges.
    e.g. [1,2,3,7,8,10] -> ["1-3", "7-8", "10-10"]
    """
    if not pages:
        return []
    ranges: list[str] = []
    start = end = pages[0]
    for p in pages[1:]:
        if p == end + 1:
            end = p
        else:
            ranges.append(f"{start}-{end}")
            start = end = p
    ranges.append(f"{start}-{end}")
    return ranges


def _find_nougat() -> str:
    """Locate the nougat executable (handles conda envs on Windows)."""
    import shutil
    exe = shutil.which("nougat")
    if exe:
        return exe
    # Derive from the current Python interpreter path (works inside conda env)
    python_dir = Path(sys.executable).parent
    for candidate in [
        python_dir / "nougat",
        python_dir / "nougat.exe",
        python_dir / "Scripts" / "nougat",
        python_dir / "Scripts" / "nougat.exe",
    ]:
        if candidate.exists():
            return str(candidate)
    return "nougat"  # fall back and let subprocess raise a clear error


def _nougat_normalize(mmd: str) -> str:
    """Convert nougat's \\(...\\) and \\[...\\] delimiters to $...$ and $$...$$ ."""
    mmd = re.sub(r"\\\[([\s\S]*?)\\\]", lambda m: f"$${m.group(1)}$$", mmd)
    mmd = re.sub(r"\\\(([\s\S]*?)\\\)", lambda m: f"${m.group(1)}$", mmd)
    return mmd


def run_nougat(pdf_path: Path, pages: Optional[str] = None) -> str:
    """Run nougat on a PDF and return the normalized MMD string."""
    import subprocess, tempfile

    nougat_exe = _find_nougat()
    cmd = [nougat_exe, str(pdf_path), "--no-skipping"]
    if pages:
        cmd += ["--pages", pages]

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd += ["-o", tmpdir]
        page_info = f" (pages {pages})" if pages else ""
        print(f"  [nougat] Running on {pdf_path.name}{page_info}...")
        proc = subprocess.run(cmd)  # no capture — lets nougat's progress bar through

        mmd_file = Path(tmpdir) / f"{pdf_path.stem}.mmd"
        if not mmd_file.exists():
            print(f"[!] nougat produced no output (exit code {proc.returncode})")
            sys.exit(1)

        mmd = mmd_file.read_text(encoding="utf-8")

    print(f"  [nougat] Done — {len(mmd):,} characters")
    return _nougat_normalize(mmd)


def run_nougat_smart(pdf_path: Path) -> str:
    """
    Two-pass approach:
      1. Fast pymupdf scan to find which pages contain theorems.
      2. Extract those pages into a temp PDF (avoids complex --pages arg).
      3. Run nougat on the temp PDF for full LaTeX output.
    Typically reduces pages processed by 60-80%.
    """
    try:
        import fitz
    except ImportError:
        print("[!] pymupdf required for smart scan.  Install: pip install pymupdf")
        sys.exit(1)

    import tempfile

    doc = fitz.open(str(pdf_path))
    total = len(doc)

    print(f"  [scan]   Scanning {total} pages for theorem keywords...")
    theorem_pages = find_theorem_pages(pdf_path)
    pct = 100 * len(theorem_pages) // total
    print(f"  [scan]   {len(theorem_pages)}/{total} pages contain theorems ({pct}%) — skipping the rest")

    if not theorem_pages:
        print("  [scan]   No theorem pages found — falling back to full OCR")
        doc.close()
        return run_nougat(pdf_path)

    # Extract theorem pages into a temp PDF — one clean file for nougat, no
    # complex --pages argument that can cause hangs with many discontiguous ranges.
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".pdf")
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)

    print(f"  [scan]   Extracting {len(theorem_pages)} pages to temp PDF...")
    out_doc = fitz.open()
    for page_num in theorem_pages:
        out_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
    out_doc.save(str(tmp_path))
    out_doc.close()
    doc.close()

    print(f"  [nougat] Running OCR on theorem pages only...")
    try:
        return run_nougat(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Markdown → theorem dicts
# ---------------------------------------------------------------------------

# Matches marker's bold-header style:  **Theorem 1.2 Name.**
_BOLD_ENV = re.compile(
    r"^\*\*("
    r"Theorem|Definition|Lemma|Proposition|Corollary|Example|Remark|Conjecture|Axiom|Property"
    r")\s*([\d.]+)?"
    r"(?:\s+([^*.(][^*.]*?))?"   # optional title before the closing ** or .
    r"[\s.]*\*\*\.?\s*",
    re.IGNORECASE,
)

# Matches plain style:  Lemma 1.2.6 Elementary matrices are...
_PLAIN_ENV = re.compile(
    r"^("
    r"Theorem|Definition|Lemma|Proposition|Corollary|Example|Remark|Conjecture|Axiom|Property"
    r")\s+([\d.]+)"
    r"(?:\s+([^(\n][^\n]*?))?"   # optional inline title
    r"\s*$",
    re.IGNORECASE,
)

_PROOF_START = re.compile(r"^[_*]?Proof[_*]?\.?[_*]?[:,.]?\s*", re.IGNORECASE)
_PROOF_END = re.compile(r"[□∎]|\\(blacksquare|square)\b|Q\.E\.D\.|\\qed\b")

_SECTION_HDR = re.compile(r"^#{1,4}\s+")   # any markdown heading — not a theorem


def _build_theorem_name(env_type: str, number: Optional[str], title: Optional[str]) -> str:
    """Assemble a clean theorem_name string."""
    name = env_type.capitalize()
    if number:
        name += f" {number}"
    if title:
        # strip trailing punctuation from the inline title
        title = title.strip().rstrip(".")
        if title:
            name += f" ({title})"
    return name


def parse_markdown(md: str, source: str) -> list[dict]:
    """
    Parse a marker-pdf markdown document into ProofWiki-format theorem dicts.

    Each dict has:
        theorem_name  str
        type          str  (theorem | lemma | definition | …)
        body          str  (LaTeX-preserving)
        proof         str  (optional)
        number        str  (optional, e.g. "1.2.6")
        note          str  (optional, inline title)
    """
    lines = md.splitlines()
    results: list[dict] = []

    current: Optional[dict] = None
    body_lines: list[str] = []
    proof_lines: list[str] = []
    in_proof = False

    def flush():
        nonlocal current, body_lines, proof_lines, in_proof
        if current is None:
            return
        body = _clean(body_lines)
        if len(body.strip()) > 15:
            current["body"] = body
            if proof_lines:
                proof = _clean(proof_lines)
                if proof.strip():
                    current["proof"] = proof
            results.append(current)
        current = None
        body_lines = []
        proof_lines = []
        in_proof = False

    for line in lines:
        stripped = line.rstrip()

        # ── skip markdown section headings (not theorems) ──────────────────
        if _SECTION_HDR.match(stripped):
            flush()
            continue

        # ── proof start (checked BEFORE proof end so "Proof...□" single-liners work)
        if current is not None and not in_proof and _PROOF_START.match(stripped):
            in_proof = True
            remainder = _PROOF_START.sub("", stripped).strip()
            # check if proof ends on the same line
            if _PROOF_END.search(remainder):
                remainder = _PROOF_END.sub("", remainder).strip()
                if remainder:
                    proof_lines.append(remainder)
                in_proof = False
            elif remainder:
                proof_lines.append(remainder)
            continue

        # ── proof end marker ────────────────────────────────────────────────
        if current is not None and _PROOF_END.search(stripped):
            content = _PROOF_END.sub("", stripped).strip()
            if in_proof:
                if content:
                    proof_lines.append(content)
                in_proof = False
            else:
                # □ in body (not preceded by "Proof") — body ends here, flush
                if content:
                    body_lines.append(content)
                flush()
            continue

        # ── theorem environment header ───────────────────────────────────────
        m = _BOLD_ENV.match(stripped) or _PLAIN_ENV.match(stripped)
        if m:
            flush()
            env_type  = m.group(1).lower()
            number    = m.group(2) if m.lastindex >= 2 else None
            raw_title = m.group(3).strip() if (m.lastindex >= 3 and m.group(3)) else None

            # for PLAIN_ENV the "title" includes the start of the body — split on sentence end
            # heuristic: title ends at first period followed by space+capital, or is short
            title = _extract_title(raw_title) if raw_title else None
            body_seed = _body_remainder(raw_title, title) if raw_title else None

            current = {"theorem_name": _build_theorem_name(env_type, number, title),
                       "type": env_type}
            if number:
                current["number"] = number
            if title:
                current["note"] = title

            # remainder of the header line is the start of the body
            after_match = stripped[m.end():].strip()
            if body_seed:
                body_lines.append(body_seed)
            if after_match:
                body_lines.append(after_match)
            continue

        # ── accumulate body / proof ─────────────────────────────────────────
        if current is not None:
            if in_proof:
                proof_lines.append(stripped)
            else:
                body_lines.append(stripped)

    flush()
    return results


def _extract_title(text: str) -> Optional[str]:
    """
    Heuristically decide if 'text' (the words after the number) is a named title
    vs. the start of the theorem body.  Short all-word phrases are titles.
    """
    if not text:
        return None
    text = text.strip().rstrip(".")
    # If it contains a LaTeX dollar sign it's body, not a title
    if "$" in text:
        return None
    words = text.split()
    # Up to ~6 title words and no lowercase function words that signal body prose
    body_starters = {"let", "suppose", "assume", "given", "if", "for", "every",
                     "the", "a", "an", "consider", "there"}
    if len(words) <= 6 and words[0].lower() not in body_starters:
        return text
    return None


def _body_remainder(raw: str, title: Optional[str]) -> Optional[str]:
    """Return the part of raw that comes after the extracted title."""
    if title is None:
        return raw.strip() if raw else None
    rest = raw[len(title):].strip().lstrip(".")
    return rest if rest else None



def _strip_markdown(text: str) -> str:
    """Remove markdown formatting but preserve LaTeX ($...$  and $$...$$)."""
    # Temporarily mask LaTeX spans so we don't touch math
    placeholders: list[str] = []

    def mask(m: re.Match) -> str:
        placeholders.append(m.group(0))
        return f"\x00{len(placeholders) - 1}\x00"

    text = re.sub(r"\$\$[\s\S]*?\$\$", mask, text)
    text = re.sub(r"\$[^$\n]+?\$", mask, text)

    # Strip bold (**text** or __text__)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    # Strip italic (*text* or _text_) — single char boundary to avoid touching math
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\1", text)
    # Strip inline code
    text = re.sub(r"`(.+?)`", r"\1", text)
    # Restore LaTeX
    text = re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], text)
    return text


def _clean(lines: list[str]) -> str:
    text = "\n".join(lines)
    text = _strip_markdown(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > 4000:
        text = text[:4000] + "..."
    return text


# ---------------------------------------------------------------------------
# Save output  (ProofWiki-compatible format)
# ---------------------------------------------------------------------------

def save_output(theorems: list[dict], source: str, output_path: Path):
    data = {"source": source, "theorems": theorems}
    tmp = str(output_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, str(output_path))
    print(f"  [save] {output_path}")


# ---------------------------------------------------------------------------
# Process one PDF
# ---------------------------------------------------------------------------

def process_pdf(
    pdf_path: Path,
    source: Optional[str] = None,
    slug: Optional[str] = None,
    pages: Optional[str] = None,
):
    slug   = slug   or re.sub(r"[^a-z0-9]+", "-", pdf_path.stem.lower()).strip("-")
    source = source or pdf_path.stem.replace("_", " ").replace("-", " ")

    output_dir = DATA_SOURCES_DIR / slug
    output_dir.mkdir(parents=True, exist_ok=True)

    # Full-run cache uses the plain name; partial runs get a suffix so they
    # never shadow the full-book cache.
    if pages:
        safe_pages = pages.replace("-", "_")
        md_cache = output_dir / f"{slug}_p{safe_pages}.mmd"
        json_path = output_dir / f"{slug}_p{safe_pages}.json"
    else:
        md_cache  = output_dir / f"{slug}.mmd"
        json_path = output_dir / f"{slug}.json"

    print(f"\n{'='*60}")
    print(f"Processing: {pdf_path.name}")
    print(f"Slug:       {slug}")
    if pages:
        print(f"Pages:      {pages}")
    print(f"{'='*60}")

    # Step 1 — OCR (or load cache)
    if md_cache.exists():
        print(f"  [nougat] Using cached MMD: {md_cache.name}")
        md = _nougat_normalize(md_cache.read_text(encoding="utf-8"))
    elif pages:
        # Explicit page range — run nougat directly on those pages (1-indexed)
        md = run_nougat(pdf_path, pages=pages)
        md_cache.write_text(md, encoding="utf-8")
        print(f"  [nougat] Cached to {md_cache.name}")
    else:
        # Smart mode: pymupdf scan first, then nougat on theorem pages only
        md = run_nougat_smart(pdf_path)
        md_cache.write_text(md, encoding="utf-8")
        print(f"  [nougat] Cached to {md_cache.name}")

    # Step 2 — Parse
    print(f"  [parse]  Extracting theorems...")
    theorems = parse_markdown(md, source)

    # Step 3 — Save
    save_output(theorems, source, json_path)

    # Summary
    counts: dict[str, int] = {}
    for t in theorems:
        counts[t["type"]] = counts.get(t["type"], 0) + 1
    print(f"  [done]  {len(theorems)} entries extracted:")
    for tp, c in sorted(counts.items()):
        print(f"          {tp}: {c}")


# ---------------------------------------------------------------------------
# Re-parse an existing cached markdown without re-running OCR
# ---------------------------------------------------------------------------

def reparse(slug: str, source: Optional[str] = None, pages: Optional[str] = None):
    output_dir = DATA_SOURCES_DIR / slug
    if pages:
        safe_pages = pages.replace("-", "_")
        md_cache  = output_dir / f"{slug}_p{safe_pages}.mmd"
        json_path = output_dir / f"{slug}_p{safe_pages}.json"
    else:
        md_cache  = output_dir / f"{slug}.mmd"
        json_path = output_dir / f"{slug}.json"

    if not md_cache.exists():
        # Show all available caches to help the user
        available = sorted(output_dir.glob(f"{slug}*.mmd")) if output_dir.exists() else []
        print(f"[error] No cached MMD at {md_cache.name}")
        if available:
            print(f"        Available caches:")
            for f in available:
                print(f"          {f.name}")
        else:
            print(f"        Run without --reparse first to generate it.")
        sys.exit(1)

    source = source or slug.replace("-", " ")
    print(f"Re-parsing cached MMD for: {slug}")
    md = _nougat_normalize(md_cache.read_text(encoding="utf-8"))
    theorems = parse_markdown(md, source)
    save_output(theorems, source, json_path)
    print(f"  [done]  {len(theorems)} entries -> {json_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Drop PDFs in input/, get structured JSON in ProofWiki format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  1. Put PDFs in the input/ folder
  2. python pdf_textbook_ingestor.py
  3. Output in data/sources/{book-name}/

The first run OCR's the PDF with marker and caches the markdown.
Subsequent re-runs re-use the cache automatically.

To tweak parsing without re-running OCR:
  python pdf_textbook_ingestor.py --reparse artin-algebra
        """
    )
    parser.add_argument("--pages",   default=None, help="Page range for OCR, e.g. '0-20'")
    parser.add_argument("--source",  default=None, help="Source string override")
    parser.add_argument("--slug",    default=None, help="Output folder name override")
    parser.add_argument("--reparse", default=None, metavar="SLUG",
                        help="Re-parse cached markdown for SLUG without re-running OCR")

    args = parser.parse_args()

    if args.reparse:
        reparse(args.reparse, source=args.source, pages=args.pages)
        return

    INPUT_DIR.mkdir(exist_ok=True)
    pdfs = sorted(INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {INPUT_DIR}")
        print(f"  Drop your PDF files there, then run again.")
        sys.exit(0)

    print(f"Found {len(pdfs)} PDF(s) in input/:")
    for p in pdfs:
        print(f"  - {p.name}")

    for pdf_path in pdfs:
        process_pdf(
            pdf_path=pdf_path,
            source=args.source,
            slug=args.slug if len(pdfs) == 1 else None,
            pages=args.pages,
        )

    print(f"\nAll done!")


if __name__ == "__main__":
    main()
