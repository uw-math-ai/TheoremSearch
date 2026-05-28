#!/usr/bin/env python3
"""
nLab Ingestor
=============
Fetches HTML from GitHub nlab-content-html repo, extracts theorems.

Output format:
{
    "theorem_name": "Theorem 1.2",
    "type": "theorem",
    "number": "1.2",
    "note": "Yoneda lemma",
    "body": "...",
    "proof": "...",
    "url": "https://ncatlab.org/nlab/show/PageName#theorem_anchor"
}

Usage:
    python nlab_ingestor.py                    # Full run (~18k pages)
    python nlab_ingestor.py --test 100         # Test with 100 pages
    python nlab_ingestor.py --local PATH       # Read from local unzipped repo (fast)
    python nlab_ingestor.py --workers 30       # Override parallel worker count
"""

import re
import json
import time
import argparse
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("[!] BeautifulSoup required. Install: pip install beautifulsoup4")
    exit(1)

# Use lxml if available - significantly faster HTML parsing
try:
    import lxml  # type: ignore[import]  # noqa: F401
    HTML_PARSER = 'lxml'
except ImportError:
    HTML_PARSER = 'html.parser'


def clean_text(element):
    """
    Extract text from a BeautifulSoup element, replacing <math> tags with
    their LaTeX source wrapped in $...$ or $$...$$.
    """
    if element is None:
        return ""

    el = BeautifulSoup(str(element), HTML_PARSER)

    for tag in el.find_all(["script", "style", "nav"]):
        tag.decompose()

    for math_tag in el.find_all("math"):
        annotation = math_tag.find("annotation", {"encoding": "application/x-tex"})
        if annotation and annotation.string:
            alttext = annotation.string.strip()
        else:
            alttext = math_tag.get("alttext", "").strip()

        if alttext:
            display = math_tag.get("display", "inline")
            replacement = f" $${alttext}$$ " if display == "block" else f" ${alttext}$ "
        else:
            replacement = " "
        math_tag.replace_with(replacement)

    text = el.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    # Strip C1 control characters (U+0080–U+009F) — encoding artifacts from
    # Windows-1252 content mis-decoded as Latin-1/Unicode (e.g. U+0096 → "–")
    text = re.sub(r'[\x80-\x9f]', '', text)
    return text


def _mask_latex(text):
    chars = list(text)
    for pattern in (r'\$\$.*?\$\$', r'\$[^$]*?\$'):
        for m in re.finditer(pattern, text, flags=re.DOTALL):
            for i in range(m.start(), m.end()):
                chars[i] = 'X'
    return ''.join(chars)


def _looks_like_note(text):
    if re.fullmatch(r'[X\s\d,]+', text):
        return False
    plain_letters = re.sub(r'\\[a-zA-Z]+', '', text)
    plain_letters = re.sub(r'[${}]', '', plain_letters)
    if not re.search(r'[a-zA-Z]', plain_letters):
        return False
    return True


def extract_parenthetical_note(text):
    masked = _mask_latex(text)
    matches = list(re.finditer(r'\(([^()]+)\)', masked))
    if not matches:
        return None
    for m in reversed(matches):
        start, end = m.start(1), m.end(1)
        candidate = text[start:end].strip()
        masked_candidate = masked[start:end].strip()
        if _looks_like_note(masked_candidate):
            return candidate
    return None


class NLabIngestor:
    """nLab ingestor - fetches from GitHub HTML repo or local directory."""

    GITHUB_API = "https://api.github.com"
    RAW_BASE = "https://raw.githubusercontent.com/ncatlab/nlab-content-html/master"
    NLAB_BASE = "https://ncatlab.org/nlab/show"

    THEOREM_CLASSES = {
        'num_theorem':  'theorem',
        'num_lemma':    'lemma',
        'num_prop':     'proposition',
        'num_cor':      'corollary',
        'num_defn':     'definition',
        'num_remark':   'remark',
        'num_example':  'example',
        'num_note':     'note',
        'un_theorem':   'theorem',
        'un_lemma':     'lemma',
        'un_prop':      'proposition',
        'un_cor':       'corollary',
        'un_defn':      'definition',
        'un_remark':    'remark',
        'un_example':   'example',
        'un_note':      'note',
    }

    # How many block-level non-theorem siblings to scan past looking for a proof
    PROOF_SCAN_LIMIT = 10

    def __init__(self, output_dir="data/nlab", token=None, local_dir=None, workers=None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.token = token
        self.local_dir = Path(local_dir) if local_dir else None
        self.workers = workers or (8 if local_dir else 20)

        self.parsed_items = []
        self.stats = {
            "total_pages": 0,
            "pages_with_theorems": 0,
            "total_theorems": 0,
            "failed": 0,
            "by_type": {},
            "with_proof": 0,
        }
        self._lock = threading.Lock()

        self.session = self._create_session()

    def _create_session(self):
        session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries, pool_connections=self.workers,
                              pool_maxsize=self.workers)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        headers = {"User-Agent": "MathCopilot/1.0 (Educational research)"}
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        session.headers.update(headers)

        return session

    def get_html_paths_remote(self):
        """Get all HTML file paths from GitHub API."""
        print("[*] Fetching file list from GitHub...")
        api_url = f"{self.GITHUB_API}/repos/ncatlab/nlab-content-html/git/trees/master?recursive=1"
        try:
            r = self.session.get(api_url, timeout=60)
            r.raise_for_status()
            data = r.json()
            if data.get("truncated"):
                print("[!] WARNING: GitHub API response was truncated. "
                      "File list is incomplete. Use --local mode for a full run.")
            paths = [item.get("path", "") for item in data.get("tree", [])
                     if item.get("path", "").endswith(".html")]
            print(f"[+] Found {len(paths)} HTML files")
            return paths
        except Exception as e:
            print(f"[!] Error fetching file list: {e}")
            return []

    def get_html_paths_local(self):
        """Get all HTML file paths from local directory."""
        print(f"[*] Scanning local directory: {self.local_dir}")
        paths = list(self.local_dir.glob("**/*.html"))
        print(f"[+] Found {len(paths)} HTML files")
        return paths

    def fetch_html_remote(self, path):
        """Fetch HTML content from GitHub."""
        url = f"{self.RAW_BASE}/{path}"
        try:
            r = self.session.get(url, timeout=30)
            if r.status_code == 200:
                return r.text
        except Exception:
            pass
        return None

    def fetch_html_local(self, path):
        """Read HTML content from local file."""
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

    def extract_page_name(self, soup):
        """Extract page name from HTML."""
        title_elem = soup.find('title')
        if title_elem:
            title = title_elem.get_text(strip=True)
            if title.endswith(' in nLab'):
                return title[:-8]
            return title
        h1 = soup.find('h1', id='pageName')
        if h1:
            return h1.get_text(strip=True)
        return None

    def _extract_proof_text(self, div):
        """Extract clean text from a proof div. Returns None if empty."""
        soup = BeautifulSoup(str(div), HTML_PARSER)
        div_copy = soup.find('div')
        if div_copy is None:
            div_copy = soup
        header = div_copy.find(['h6', 'strong', 'b'])
        if header:
            header.decompose()
        text = clean_text(div_copy)
        return text if text else None

    # Tags whose presence should NOT burn a skip slot — inline/trivial content
    _INLINE_TAGS = frozenset({'a', 'span', 'br', 'hr', 'script', 'style'})

    def _find_following_proof(self, div):
        """
        Look for a div.proof following a theorem div.

        Only block-level HTML elements (not text nodes or inline tags like <a>)
        count toward PROOF_SCAN_LIMIT, so citation snippets like "(e.g. ref1, ref2)."
        that appear between a theorem and its proof don't falsely exhaust the budget.
        """
        skip_count = 0
        for sibling in div.next_siblings:
            # Text nodes (including NavigableString) never consume a skip slot
            if isinstance(sibling, str):
                continue
            if not hasattr(sibling, 'get'):
                continue

            classes = sibling.get('class', [])

            if 'proof' in classes:
                return self._extract_proof_text(sibling)

            # Stop if we hit the next theorem block
            if any(c in self.THEOREM_CLASSES for c in classes):
                break

            # Check for proof nested inside a wrapper element
            # (nLab sometimes wraps in toggle/spoiler divs)
            inner_proof = sibling.find('div', class_='proof') if hasattr(sibling, 'find') else None
            if inner_proof:
                return self._extract_proof_text(inner_proof)

            # Only count block-level elements toward the skip budget
            if sibling.name not in self._INLINE_TAGS:
                skip_count += 1
                if skip_count > self.PROOF_SCAN_LIMIT:
                    break

        return None

    def extract_theorems(self, html_content):
        """Extract theorems from HTML using a single pass over all theorem divs."""
        soup = BeautifulSoup(html_content, HTML_PARSER)
        page_name = self.extract_page_name(soup)
        if not page_name:
            return []
        base_url = f"{self.NLAB_BASE}/{page_name.replace(' ', '+')}"

        # Single find_all with regex instead of 18 separate calls
        theorem_class_re = re.compile(
            r'^(num|un)_(theorem|lemma|prop|cor|defn|remark|example|note)$'
        )
        theorems = []
        seen_ids = set()

        for div in soup.find_all('div', class_=theorem_class_re):
            # Determine type from first matching class
            theorem_type = None
            for cls in div.get('class', []):
                if cls in self.THEOREM_CLASSES:
                    theorem_type = self.THEOREM_CLASSES[cls]
                    break
            if not theorem_type:
                continue

            # Deduplicate by div id
            div_id = div.get('id', '')
            if div_id and div_id in seen_ids:
                continue
            if div_id:
                seen_ids.add(div_id)

            theorem = self._parse_theorem_div(div, theorem_type, base_url)
            if theorem:
                theorems.append(theorem)

        return theorems

    def _parse_theorem_div(self, div, theorem_type, base_url):
        """Parse a theorem div into structured fields."""
        theorem_id = div.get('id', '')
        if not theorem_id:
            anchor = div.find('a', id=True)
            if anchor:
                theorem_id = anchor.get('id', '')

        url = f"{base_url}#{theorem_id}" if theorem_id else base_url

        div_copy = BeautifulSoup(str(div), HTML_PARSER).find('div')

        header = div_copy.find(['h6', 'strong', 'b']) if div_copy else None
        header_text = ""
        if header:
            header_text = clean_text(header)
            header.decompose()

        body = clean_text(div_copy)

        if not body or len(body) < 10:
            return None

        theorem_name = header_text if header_text else theorem_type.capitalize()

        number = None
        number_match = re.search(
            r'^(?:Theorem|Lemma|Proposition|Corollary|Definition|Remark|Example|Note)\s+'
            r'([a-zA-Z]?\d+(?:\.\d+)*(?:[a-z])?)',
            header_text, re.IGNORECASE
        )
        if number_match:
            number = number_match.group(1)

        note = extract_parenthetical_note(header_text)

        if not note:
            body_match = re.match(r'^\s*\(([^)]+)\)\s*', body)
            if body_match:
                candidate = body_match.group(1)
                if _looks_like_note(_mask_latex(candidate)):
                    note = candidate.strip()
                    # Don't strip note from body: the regex stops at the first ")"
                    # which may land inside a LaTeX expression, leaving a garbled fragment.

        proof_text = self._find_following_proof(div)

        result = {
            "theorem_name": theorem_name,
            "type": theorem_type,
            "body": body,
            "url": url,
        }

        if number:
            result["number"] = number
        if note:
            result["note"] = note
        if proof_text:
            result["proof"] = proof_text

        return result

    def process_file(self, path):
        """Process one HTML file. Returns list of extracted theorems."""
        if self.local_dir:
            html = self.fetch_html_local(path)
        else:
            html = self.fetch_html_remote(path)

        if not html:
            return []

        return self.extract_theorems(html)

    def _collect_results(self, theorems):
        """Thread-safe accumulation of results."""
        with self._lock:
            for thm in theorems:
                self.parsed_items.append(thm)
                t = thm["type"]
                self.stats["by_type"][t] = self.stats["by_type"].get(t, 0) + 1
                if "proof" in thm:
                    self.stats["with_proof"] += 1
            if theorems:
                self.stats["pages_with_theorems"] += 1
                self.stats["total_theorems"] += len(theorems)

    def run(self, limit=None):
        """Main loop - parallel processing."""
        print("\n" + "="*60)
        print("nLab Ingestor")
        print(f"Parser: {HTML_PARSER} | Workers: {self.workers}")
        print("="*60)

        if self.local_dir:
            paths = self.get_html_paths_local()
        else:
            paths = self.get_html_paths_remote()

        if not paths:
            print("[!] No files found!")
            return

        if limit:
            paths = paths[:limit]
            print(f"[*] Limiting to {limit} files")

        self.stats["total_pages"] = len(paths)
        total = len(paths)
        completed = [0]  # mutable for closure

        print(f"\n[*] Processing {total} files with {self.workers} workers...")
        start_time = time.time()

        def worker(path):
            try:
                return self.process_file(path)
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {executor.submit(worker, p): p for p in paths}
            for future in as_completed(futures):
                result = future.result()
                if result is None:
                    with self._lock:
                        self.stats["failed"] += 1
                else:
                    self._collect_results(result)

                with self._lock:
                    completed[0] += 1
                    done = completed[0]

                if done % 500 == 0:
                    with self._lock:
                        n_thm = self.stats["total_theorems"]
                    elapsed = time.time() - start_time
                    rate = done / elapsed
                    eta = (total - done) / rate if rate > 0 else 0
                    print(f"    [{done}/{total}] {n_thm} items | "
                          f"{rate:.1f}/sec | ETA: {eta/60:.1f} min")

        self._save_output()
        self._print_summary(time.time() - start_time)

    def _save_output(self):
        print("\n[*] Saving output...")
        output_file = self.output_dir / "nlab.json"
        output_data = {
            "source": "https://ncatlab.org/nlab/",
            "theorems": self.parsed_items
        }
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"    Saved {len(self.parsed_items)} items -> {output_file}")

    def _print_summary(self, elapsed):
        pages_total = self.stats['total_pages']
        pages_with = self.stats['pages_with_theorems']
        n_total = self.stats['total_theorems']
        n_proof = self.stats['with_proof']
        density = n_total / pages_with if pages_with else 0

        print("\n" + "="*60)
        print("COMPLETE")
        print("="*60)
        print(f"Total pages scanned:          {pages_total}")
        print(f"Pages with formal theorems:   {pages_with} "
              f"({100*pages_with//pages_total if pages_total else 0}%)")
        print(f"Items per theorem-page:       {density:.1f}")
        print(f"  (Many nLab pages are prose-only — no formal theorem blocks)")
        print(f"Failed:                       {self.stats['failed']}")
        print(f"Time:                         {elapsed/60:.1f} minutes")
        print("\n" + "-"*60)
        print("FINAL COUNTS")
        print("-"*60)
        by_type = self.stats.get("by_type", {})
        from collections import Counter
        by_proof = Counter(thm["type"] for thm in self.parsed_items if "proof" in thm)
        total = 0
        provable_total = 0
        provable_with_proof = 0
        provable_types = {"theorem", "lemma", "proposition", "corollary"}
        for t in ["theorem", "lemma", "proposition", "corollary",
                  "definition", "remark", "example", "note"]:
            count = by_type.get(t, 0)
            with_p = by_proof.get(t, 0)
            pct = f"({100*with_p//count}% proved)" if count else ""
            total += count
            print(f"  {(t.upper() + 'S'):<20} {count:>6}  {with_p:>5} proofs  {pct}")
            if t in provable_types:
                provable_total += count
                provable_with_proof += with_p
        print("-"*60)
        print(f"  {'TOTAL':<20} {total:>6}  {n_proof:>5} proofs  "
              f"({100*n_proof//total if total else 0}% overall)")
        if provable_total:
            print(f"  Thm/Lem/Prop/Cor:       {provable_total:>6}  "
                  f"{provable_with_proof:>5} proofs  "
                  f"({100*provable_with_proof//provable_total}% of provable types)")
        print("="*60)


def main():
    parser = argparse.ArgumentParser(description="Ingest nLab theorems")
    parser.add_argument("--output", "-o", default="data/nlab")
    parser.add_argument("--test", "-t", type=int, default=None,
                        help="Limit to N files (for testing)")
    parser.add_argument("--token", default=None,
                        help="GitHub personal access token (raises API rate limit)")
    parser.add_argument("--local", default=None,
                        help="Path to local unzipped nlab-content-html repo (fast mode)")
    parser.add_argument("--workers", type=int, default=None,
                        help="Number of parallel workers (default: 20 remote, 8 local)")

    args = parser.parse_args()

    NLabIngestor(
        output_dir=args.output,
        token=args.token,
        local_dir=args.local,
        workers=args.workers,
    ).run(limit=args.test)


if __name__ == "__main__":
    main()
