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
"""

import re
import json
import time
import argparse
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("[!] BeautifulSoup required. Install: pip install beautifulsoup4")
    exit(1)


class NLabIngestor:
    """nLab ingestor - fetches from GitHub HTML repo."""

    GITHUB_API = "https://api.github.com"
    RAW_BASE = "https://raw.githubusercontent.com/ncatlab/nlab-content-html/master"
    NLAB_BASE = "https://ncatlab.org/nlab/show"

    # CSS classes for theorem-like content (proofs handled separately)
    THEOREM_CLASSES = {
        'num_theorem': 'theorem',
        'num_lemma': 'lemma',
        'num_prop': 'proposition',
        'num_cor': 'corollary',
        'num_def': 'definition',
        'num_remark': 'remark',
    }

    def __init__(self, output_dir="data/nlab", token=None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.token = token

        self.parsed_items = []
        self.stats = {
            "total_pages": 0,
            "pages_with_theorems": 0,
            "total_theorems": 0,
            "failed": 0,
            "by_type": {},
            "with_proof": 0,
        }

        self.session = self._create_session()

    def _create_session(self):
        session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        headers = {"User-Agent": "MathCopilot/1.0 (Educational research)"}
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        session.headers.update(headers)

        return session

    def get_html_paths(self):
        """Get all HTML file paths from GitHub."""
        print("[*] Fetching file list from GitHub...")

        api_url = f"{self.GITHUB_API}/repos/ncatlab/nlab-content-html/git/trees/master?recursive=1"

        try:
            r = self.session.get(api_url, timeout=60)
            r.raise_for_status()
            data = r.json()

            paths = []
            for item in data.get("tree", []):
                path = item.get("path", "")
                if path.endswith(".html"):
                    paths.append(path)

            print(f"[+] Found {len(paths)} HTML files")
            return paths

        except Exception as e:
            print(f"[!] Error: {e}")
            return []

    def fetch_html(self, path):
        """Fetch HTML content from GitHub."""
        url = f"{self.RAW_BASE}/{path}"

        try:
            r = self.session.get(url, timeout=30)
            if r.status_code == 200:
                return r.text
        except:
            pass
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
        """Extract plain text from a proof div."""
        div_copy = BeautifulSoup(str(div), 'html.parser').find('div')

        # Remove header if present
        header = div_copy.find(['h6', 'strong', 'b'])
        if header:
            header.decompose()

        text = div_copy.get_text(separator=' ', strip=True)
        return re.sub(r'\s+', ' ', text).strip()

    def _find_following_proof(self, div):
        """Look for a div.proof immediately following a theorem div."""
        for sibling in div.next_siblings:
            # Skip whitespace/newline text nodes
            if isinstance(sibling, str):
                continue
            # If the very next tag is a proof div, grab it
            if hasattr(sibling, 'get') and 'proof' in sibling.get('class', []):
                return self._extract_proof_text(sibling)
            # Stop if we hit another block-level element that isn't a proof
            break
        return None

    def extract_theorems(self, html_content):
        """Extract theorems from HTML."""
        theorems = []
        soup = BeautifulSoup(html_content, 'html.parser')

        page_name = self.extract_page_name(soup)
        if not page_name:
            return []

        base_url = f"{self.NLAB_BASE}/{page_name.replace(' ', '+')}"

        for css_class, theorem_type in self.THEOREM_CLASSES.items():
            for div in soup.find_all('div', class_=css_class):
                theorem = self._parse_theorem_div(div, theorem_type, base_url)
                if theorem:
                    theorems.append(theorem)

        return theorems

    def _parse_theorem_div(self, div, theorem_type, base_url):
        """Parse a theorem div into structured fields."""
        # Get anchor/id for direct link
        theorem_id = div.get('id', '')

        if not theorem_id:
            anchor = div.find('a', id=True)
            if anchor:
                theorem_id = anchor.get('id', '')

        url = f"{base_url}#{theorem_id}" if theorem_id else base_url

        # Clone div for parsing
        div_copy = BeautifulSoup(str(div), 'html.parser').find('div')

        # Get header text
        header = div_copy.find(['h6', 'strong', 'b'])
        header_text = ""
        if header:
            header_text = header.get_text(strip=True)
            header.decompose()

        # Get body
        body = div_copy.get_text(separator=' ', strip=True)
        body = re.sub(r'\s+', ' ', body).strip()

        if not body or len(body) < 10:
            return None

        number = None
        note = None
        theorem_name = header_text if header_text else theorem_type.capitalize()

        # Extract number (e.g. "Theorem 1.2" -> "1.2", "Lemma a1" -> "a1")
        number_match = re.search(
            r'^(?:Theorem|Lemma|Proposition|Corollary|Definition|Remark)\s+([a-zA-Z]?\d+(?:\.\d+)*(?:[a-z])?)',
            header_text, re.IGNORECASE
        )
        if number_match:
            number = number_match.group(1)

        # Extract note from header (e.g. "(Yoneda lemma)")
        note_match = re.search(r'\(([^)]+)\)', header_text)
        if note_match:
            note = note_match.group(1).strip()

        # Fallback: check start of body
        if not note:
            body_note_match = re.match(r'^\s*\(([^)]+)\)\s*', body)
            if body_note_match:
                note = body_note_match.group(1).strip()
                body = body[body_note_match.end():].strip()

        # Look for an immediately following proof div
        proof_text = self._find_following_proof(div)

        # Build result
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
        """Process one HTML file."""
        html = self.fetch_html(path)
        if not html:
            return 0

        theorems = self.extract_theorems(html)
        if not theorems:
            return 0

        for thm in theorems:
            self.parsed_items.append(thm)
            t = thm["type"]
            self.stats["by_type"][t] = self.stats["by_type"].get(t, 0) + 1
            if "proof" in thm:
                self.stats["with_proof"] += 1

        return len(theorems)

    def run(self, limit=None):
        """Main loop."""
        print("\n" + "="*60)
        print("nLab Ingestor")
        print("="*60)

        paths = self.get_html_paths()
        if not paths:
            print("[!] No files found!")
            return

        if limit:
            paths = paths[:limit]
            print(f"[*] Limiting to {limit} files")

        self.stats["total_pages"] = len(paths)
        total = len(paths)

        print(f"\n[*] Processing {total} files...")
        start_time = time.time()

        for i, path in enumerate(paths):
            try:
                count = self.process_file(path)

                if count > 0:
                    self.stats["pages_with_theorems"] += 1
                    self.stats["total_theorems"] += count

                if (i + 1) % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = (i + 1) / elapsed
                    eta = (total - i - 1) / rate if rate > 0 else 0
                    print(f"    [{i+1}/{total}] {self.stats['total_theorems']} theorems | "
                          f"{rate:.1f}/sec | ETA: {eta/60:.1f} min")

                time.sleep(0.1)

            except KeyboardInterrupt:
                print("\n[!] Interrupted! Saving...")
                break
            except:
                self.stats["failed"] += 1

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
        print("\n" + "="*60)
        print("COMPLETE")
        print("="*60)
        print(f"Total pages scanned:    {self.stats['total_pages']}")
        print(f"Pages with theorems:    {self.stats['pages_with_theorems']}")
        print(f"Failed:                 {self.stats['failed']}")
        print(f"Time:                   {elapsed/60:.1f} minutes")

        print("\n" + "-"*60)
        print("FINAL COUNTS")
        print("-"*60)

        by_type = self.stats.get("by_type", {})
        total = 0
        for t in ["theorem", "lemma", "proposition", "corollary", "definition", "remark"]:
            count = by_type.get(t, 0)
            total += count
            print(f"  {(t.upper() + 'S'):<20} {count:>6}")

        print("-"*60)
        print(f"  {'TOTAL':<20} {total:>6}")
        print(f"  {'WITH PROOF':<20} {self.stats['with_proof']:>6}")
        print("="*60)


def main():
    parser = argparse.ArgumentParser(description="Ingest nLab content")
    parser.add_argument("--output", "-o", default="data/nlab", help="Output directory")
    parser.add_argument("--test", "-t", type=int, default=None, help="Limit files")
    parser.add_argument("--token", default=None, help="GitHub token (optional)")

    args = parser.parse_args()

    ingestor = NLabIngestor(output_dir=args.output, token=args.token)
    ingestor.run(limit=args.test)


if __name__ == "__main__":
    main()