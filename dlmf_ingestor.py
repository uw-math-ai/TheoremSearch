"""
DLMF (NIST Digital Library of Mathematical Functions) Ingestor
===============================================================
Scrapes all 36 chapters of https://dlmf.nist.gov/ and extracts
section/subsection entries with formulas, definitions, and keywords.

DLMF structure:
  Chapter  : dlmf.nist.gov/1          (e.g. "Algebraic and Analytic Methods")
  Section  : dlmf.nist.gov/1.2        (e.g. "Elementary Algebra")
  Subsect. : dlmf.nist.gov/1.2.i      (e.g. "Binomial Coefficients")

Each subsection contains keyword tags, "Defines:" annotations, and formula
prose. We treat each subsection as one record.

Output JSON fields:
  dlmf_id      : e.g. "1.2.i"
  chapter      : chapter number (int)
  chapter_title: e.g. "Algebraic and Analytic Methods"
  section      : e.g. "1.2"
  section_title: e.g. "Elementary Algebra"
  subsection   : e.g. "1.2.i"  (None for section-level entries)
  title        : subsection title e.g. "Binomial Coefficients"
  defines      : list of terms defined, e.g. ["binomial coefficient"]
  keywords     : list of keyword strings
  body         : plain-text prose content
  url          : canonical URL

Usage:
  python dlmf_ingestor.py                   # full run
  python dlmf_ingestor.py --chapters 1 2 3  # specific chapters
  python dlmf_ingestor.py --test            # chapter 1 only
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://dlmf.nist.gov"
OUTPUT_FILE = "dlmf_entries.json"
CHECKPOINT_FILE = "dlmf_checkpoint.json"
CHECKPOINT_EVERY = 5  # chapters

# All 36 DLMF chapters
ALL_CHAPTERS = list(range(1, 37))

HEADERS = {
    "User-Agent": "MathCopilot-Research-Ingestor/1.0 (UW Math AI Lab; academic research)",
    "Accept": "text/html",
}

RATE_LIMIT_SECONDS = 1.0  # be polite - 1 req/sec


def fetch_page(url: str, retries: int = 3) -> BeautifulSoup | None:
    for attempt in range(retries):
        try:
            time.sleep(RATE_LIMIT_SECONDS)
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "html.parser")
            elif resp.status_code == 404:
                return None
            else:
                print(f"  HTTP {resp.status_code} for {url}, attempt {attempt+1}")
                time.sleep(2 ** attempt)
        except Exception as e:
            print(f"  Error fetching {url}: {e}, attempt {attempt+1}")
            time.sleep(2 ** attempt)
    return None


def get_chapter_title(chapter_num: int) -> str | None:
    """Fetch chapter page and extract its title."""
    url = f"{BASE_URL}/{chapter_num}"
    soup = fetch_page(url)
    if not soup:
        return None
    # Title is in the first h1
    h1 = soup.find("h1")
    if h1:
        # Strip leading section number like "Chapter 1 "
        text = h1.get_text(strip=True)
        text = re.sub(r"^Chapter\s+\d+\s*", "", text)
        return text
    return None


def get_section_links(chapter_num: int) -> list[str]:
    """
    Get all section IDs for a chapter (e.g. ["1.1", "1.2", "1.3"]).
    Parses the chapter TOC page.
    """
    url = f"{BASE_URL}/{chapter_num}"
    soup = fetch_page(url)
    if not soup:
        return []

    sections = []
    # Look for links matching pattern /1.1, /1.2, etc.
    pattern = re.compile(rf"^/{chapter_num}\.\d+$")
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Handle relative hrefs like ./1.2
        href = href.lstrip(".")
        if pattern.match(href):
            sec_id = href.lstrip("/")
            if sec_id not in seen:
                seen.add(sec_id)
                sections.append(sec_id)

    return sorted(sections, key=lambda s: [int(x) for x in s.split(".")])


def parse_section(section_id: str, chapter_title: str) -> list[dict]:
    """
    Parse a section page (e.g. 1.2) and extract all subsection records.
    Returns a list of entry dicts.
    """
    chapter_num = int(section_id.split(".")[0])
    url = f"{BASE_URL}/{section_id}"
    soup = fetch_page(url)
    if not soup:
        return []

    # Get section title from the page h1
    h1 = soup.find("h1")
    section_title = ""
    if h1:
        text = h1.get_text(strip=True)
        # Strip leading "§1.2 "
        text = re.sub(r"^§[\d.]+\s*", "", text)
        section_title = text

    entries = []

    # Find all subsection headers (h2, h3, h4 with subsection IDs)
    # DLMF uses ## §1.2(i) Binomial Coefficients
    # In parsed HTML these become h2/h3 elements with id attributes
    subsection_pattern = re.compile(
        rf"^{re.escape(section_id)}\(([ivxlcdmIVXLCDM]+)\)$"
    )

    # Strategy: find all h2/h3 elements that look like subsection headers
    # Then collect content until the next such header
    all_headers = soup.find_all(["h2", "h3", "h4", "h5"])

    subsection_blocks = []
    current_header = None
    current_content = []

    for tag in soup.descendants:
        if tag.name in ("h2", "h3", "h4"):
            # Save previous block
            if current_header is not None:
                subsection_blocks.append((current_header, current_content))
            current_header = tag
            current_content = []
        elif current_header is not None and hasattr(tag, "get_text"):
            # Only collect direct siblings, not deeply nested
            pass

    # Alternative approach: find subsection divs or sections
    # DLMF wraps subsections in <div class="subsection"> or similar
    subsections = soup.find_all(
        "div", class_=re.compile(r"subsection|ltx_subsection")
    )

    if subsections:
        for sub in subsections:
            entry = parse_subsection_div(
                sub, section_id, section_title, chapter_num, chapter_title, url
            )
            if entry:
                entries.append(entry)
    else:
        # Fall back: treat entire section as one entry
        entry = parse_full_section(
            soup, section_id, section_title, chapter_num, chapter_title, url
        )
        if entry:
            entries.append(entry)

    # Also look for explicit subsection links in the TOC
    # If we found nothing via divs, try header-based parsing
    if not entries:
        entries = parse_by_headers(
            soup, section_id, section_title, chapter_num, chapter_title, url
        )

    return entries


def clean_text(element) -> str:
    """Extract text from a BeautifulSoup element, replacing <math> tags with their LaTeX alttext."""
    if element is None:
        return ""

    # Work on a copy so we don't mutate the tree
    import copy
    el = copy.copy(element)

    # Remove nav/script/style noise
    for tag in el.find_all(["script", "style", "nav"]):
        tag.decompose()

    # Replace every <math> element with its alttext wrapped in $...$
    # alttext contains the raw LaTeX that LaTeXML stored when generating the MathML
    for math_tag in el.find_all("math"):
        alttext = math_tag.get("alttext", "").strip()
        if alttext:
            # Inline math → $...$, display math → $$...$$
            display = math_tag.get("display", "inline")
            if display == "block":
                replacement = f" $${alttext}$$ "
            else:
                replacement = f" ${alttext}$ "
        else:
            # No alttext: fall back to Unicode text content of the MathML
            replacement = f" {math_tag.get_text(strip=True)} "
        math_tag.replace_with(replacement)

    text = el.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("ⓘ", "").strip()
    return text


def extract_defines(element) -> list[str]:
    """Find 'Defines: X, Y' annotations in an element."""
    defines = []
    text = clean_text(element)
    # Look for "Defines:\n   term1, term2" patterns
    m = re.search(r"Defines?:\s*(.*?)(?:Keywords?:|Notes?:|See also:|$)", text, re.DOTALL)
    if m:
        raw = m.group(1).strip()
        # Split on commas or newlines
        terms = re.split(r"[,\n]+", raw)
        for t in terms:
            t = t.strip().strip(":")
            # Remove content in parens like "(notation)"
            t = re.sub(r"\(.*?\)", "", t).strip()
            if t and len(t) < 100:
                defines.append(t)
    return defines


def extract_keywords(element) -> list[str]:
    """Find 'Keywords: X, Y' annotations."""
    keywords = []
    text = clean_text(element)
    m = re.search(r"Keywords?:\s*(.*?)(?:Notes?:|Defines?:|Referenced by:|See also:|Permalink:|$)", text, re.DOTALL)
    if m:
        raw = m.group(1).strip()
        terms = re.split(r"[,\n]+", raw)
        for t in terms:
            t = t.strip()
            # Skip if it looks like sentence body (too long or starts with capital + space pattern)
            if t and len(t) < 60 and not re.match(r"[A-Z][a-z]+ [a-z]", t):
                keywords.append(t)
    return keywords


def parse_subsection_div(
    div, section_id: str, section_title: str, chapter_num: int,
    chapter_title: str, base_url: str
) -> dict | None:
    """Parse a single subsection div."""
    # Get the subsection header
    header = div.find(["h2", "h3", "h4", "h5", "h6"])
    if not header:
        return None

    header_text = header.get_text(strip=True)
    # Extract subsection ID and title from "§1.2(i) Binomial Coefficients"
    m = re.match(r"§([\d.]+\([ivxlcdmIVXLCDM]+\))\s*(.*)", header_text)
    subsection_id = None
    title = header_text
    if m:
        subsection_id = m.group(1)
        title = m.group(2).strip()
    else:
        # Try simpler pattern
        m2 = re.match(r"§([\d.]+)\s*(.*)", header_text)
        if m2:
            subsection_id = m2.group(1)
            title = m2.group(2).strip()

    # Get permalink if available
    permalink = div.find("a", string=re.compile(r"dlmf\.nist\.gov"))
    entry_url = f"{BASE_URL}/{subsection_id}" if subsection_id else base_url

    body = clean_text(div)
    defines = extract_defines(div)
    keywords = extract_keywords(div)

    dlmf_id = subsection_id or section_id

    return {
        "dlmf_id": dlmf_id,
        "chapter": chapter_num,
        "chapter_title": chapter_title,
        "section": section_id,
        "section_title": section_title,
        "subsection": subsection_id,
        "title": title,
        "defines": defines,
        "keywords": keywords,
        "body": body[:2000],  # cap at 2k chars
        "url": entry_url,
    }


def parse_full_section(
    soup, section_id: str, section_title: str, chapter_num: int,
    chapter_title: str, url: str
) -> dict | None:
    """Treat entire section as one entry (fallback)."""
    # Get main content area - skip nav/header/footer
    main = soup.find("div", class_=re.compile(r"ltx_page_main|main|content"))
    if not main:
        main = soup.find("body")
    if not main:
        return None

    body = clean_text(main)
    if not body or len(body) < 20:
        return None

    defines = extract_defines(main)
    keywords = extract_keywords(main)

    return {
        "dlmf_id": section_id,
        "chapter": chapter_num,
        "chapter_title": chapter_title,
        "section": section_id,
        "section_title": section_title,
        "subsection": None,
        "title": section_title,
        "defines": defines,
        "keywords": keywords,
        "body": body[:2000],
        "url": url,
    }


def parse_by_headers(
    soup, section_id: str, section_title: str, chapter_num: int,
    chapter_title: str, base_url: str
) -> list[dict]:
    """Parse subsections by finding h3/h2 headers and content between them."""
    entries = []

    # Find all subsection headers by their ID attributes
    # DLMF pages use <h3 id="i"> etc.
    headers = []
    for tag in soup.find_all(["h2", "h3", "h4"]):
        text = tag.get_text(strip=True)
        if re.match(r"§[\d.]+", text):
            headers.append(tag)

    if not headers:
        return []

    for i, header in enumerate(headers):
        header_text = header.get_text(strip=True)
        m = re.match(r"§([\d.(ivxlcdmIVXLCDM)]+)\s*(.*)", header_text)
        subsection_id = None
        title = header_text
        if m:
            subsection_id = m.group(1)
            title = m.group(2).strip() or header_text

        # Collect content between this header and the next
        content_tags = []
        sib = header.find_next_sibling()
        next_header = headers[i + 1] if i + 1 < len(headers) else None

        while sib and sib != next_header:
            content_tags.append(sib)
            sib = sib.find_next_sibling()

        # Build a temporary container for text extraction
        body_parts = []
        defines = []
        keywords = []
        for tag in content_tags:
            if hasattr(tag, "get_text"):
                body_parts.append(clean_text(tag))
                defines.extend(extract_defines(tag))
                keywords.extend(extract_keywords(tag))

        body = re.sub(r"\s+", " ", " ".join(body_parts)).strip()[:2000]

        entry_url = f"{BASE_URL}/{subsection_id}" if subsection_id else base_url

        dlmf_id = subsection_id or section_id
        entries.append({
            "dlmf_id": dlmf_id,
            "chapter": chapter_num,
            "chapter_title": chapter_title,
            "section": section_id,
            "section_title": section_title,
            "subsection": subsection_id,
            "title": title,
            "defines": list(set(defines)),
            "keywords": list(set(keywords)),
            "body": body,
            "url": entry_url,
        })

    return entries


def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {"completed_chapters": [], "entry_count": 0}


def save_checkpoint(completed_chapters: list[int], entry_count: int):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"completed_chapters": completed_chapters, "entry_count": entry_count}, f)


def load_existing_entries() -> list[dict]:
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            return json.load(f)
    return []


def save_entries(entries: list[dict]):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def ingest_chapter(chapter_num: int) -> list[dict]:
    print(f"\nChapter {chapter_num}...")
    chapter_title = get_chapter_title(chapter_num) or f"Chapter {chapter_num}"
    print(f"  Title: {chapter_title}")

    sections = get_section_links(chapter_num)
    print(f"  Sections: {sections}")

    all_entries = []
    for sec_id in sections:
        print(f"    Parsing section {sec_id}...", end=" ", flush=True)
        entries = parse_section(sec_id, chapter_title)
        print(f"{len(entries)} entries")
        all_entries.extend(entries)

    return all_entries


def main():
    parser = argparse.ArgumentParser(description="DLMF ingestor")
    parser.add_argument("--chapters", nargs="*", type=int, help="Specific chapters to ingest")
    parser.add_argument("--test", action="store_true", help="Test with chapter 1 only")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    args = parser.parse_args()

    if args.test:
        chapters_to_run = [1]
    elif args.chapters:
        chapters_to_run = args.chapters
    else:
        chapters_to_run = ALL_CHAPTERS

    checkpoint = load_checkpoint() if args.resume else {"completed_chapters": [], "entry_count": 0}
    completed = set(checkpoint["completed_chapters"])

    all_entries = load_existing_entries() if args.resume else []
    print(f"Starting DLMF ingestor. Chapters: {chapters_to_run}")
    print(f"Already completed: {sorted(completed)}")

    chapters_done_this_run = []

    for ch in chapters_to_run:
        if ch in completed:
            print(f"Chapter {ch}: already done, skipping.")
            continue

        entries = ingest_chapter(ch)
        all_entries.extend(entries)
        completed.add(ch)
        chapters_done_this_run.append(ch)

        print(f"  Chapter {ch} done: {len(entries)} entries (total: {len(all_entries)})")

        # Checkpoint
        if len(chapters_done_this_run) % CHECKPOINT_EVERY == 0:
            save_entries(all_entries)
            save_checkpoint(list(completed), len(all_entries))
            print(f"  [Checkpoint saved]")

    save_entries(all_entries)
    save_checkpoint(list(completed), len(all_entries))
    print(f"\nDone. Total entries: {len(all_entries)}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()