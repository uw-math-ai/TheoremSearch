#!/usr/bin/env python3
"""
FindStat Ingestor
=================
Fetches combinatorial statistics from the FindStat database (https://www.findstat.org/).

Page structure (from HTML analysis):
  Lines like:
    "St000041"          <- identifier
    ":"
    "Perfect matchings" <- collection
    "⟶ ℤ"
    "Values"
    "[(1,2)]=>0"        <- value lines
    ...
    "Description"
    "The number of nestings..." <- name (first line)
    "This is the number of..."  <- description body
    "References"
    "[1]  Author..."    <- references
    "Code"
    "def statistic(x):..."

Usage:
    python findstat_ingestor.py --test 10
    python findstat_ingestor.py
    python findstat_ingestor.py --start 100 --end 500
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
    print("[!] BeautifulSoup4 not installed. Run: pip install beautifulsoup4")
    raise


class FindStatIngestor:

    PAGE_URL = "https://www.findstat.org/StatisticsDatabase/{stat_id}/"
    MAX_STAT = 2100

    def __init__(self, output_dir="data/findstat"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.parsed_items = []
        self.seen_ids = set()
        self.stats = {"attempted": 0, "successful": 0, "not_found": 0, "failed": 0}
        self.session = self._create_session()

    def _create_session(self):
        session = requests.Session()
        retries = Retry(total=4, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers["User-Agent"] = "MathCopilot/1.0 (Educational research)"
        return session

    def _fetch_lines(self, stat_id):
        """Fetch page and return list of non-empty stripped text lines."""
        url = self.PAGE_URL.format(stat_id=stat_id)
        try:
            r = self.session.get(url, timeout=20)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            full_text = soup.get_text(separator="\n")
            return [l.strip() for l in full_text.splitlines() if l.strip()]
        except Exception as e:
            print(f"    [!] Fetch error ({stat_id}): {e}")
            return None

    def _parse(self, stat_id, lines):
        """
        Parse lines based on known FindStat page structure.
        Returns dict or None if this is a missing/invalid stat.
        """
        # --- Detect if this is a real statistic page ---
        # Real pages have the stat id followed by ":" then collection name.
        # Missing stat pages don't have the identifier block in the content area.
        # We look for the exact pattern: stat_id appears, then ":" nearby, then collection.
        try:
            id_idx = lines.index(stat_id)
        except ValueError:
            return None  # stat id not found in page content at all

        # The line after the id should be ":" and the one after that the collection
        if id_idx + 2 >= len(lines):
            return None
        if lines[id_idx + 1] != ":":
            return None

        collection = lines[id_idx + 2]
        # Sanity check: next line should be the arrow symbol
        if id_idx + 3 < len(lines) and lines[id_idx + 3] not in ("⟶ ℤ", "-> Z", "→ ℤ"):
            # Still accept it but just move on
            pass

        # --- Values ---
        # All lines containing "=>" that look like combinatorial object => integer
        values_lines = [
            l for l in lines
            if "=>" in l and l.startswith("[") and not l.startswith("//")
        ]
        values_str = " ".join(values_lines) if values_lines else None
        if values_str:
            values_str = re.sub(r'\s+', ' ', values_str).strip()

        # --- Description ---
        # Find "Description" heading, then grab lines until next known heading
        name = None
        description = None
        STOP_HEADINGS = {"References", "Code", "Created", "Updated", "Search"}
        try:
            desc_idx = lines.index("Description")
            desc_lines = []
            for l in lines[desc_idx + 1:]:
                if l in STOP_HEADINGS:
                    break
                desc_lines.append(l)
            if desc_lines:
                name = desc_lines[0]
                description = "\n".join(desc_lines).strip()
        except ValueError:
            pass

        # --- References ---
        references = None
        try:
            ref_idx = lines.index("References")
            ref_lines = []
            for l in lines[ref_idx + 1:]:
                if l in STOP_HEADINGS or l == "Code":
                    break
                ref_lines.append(l)
            # Merge consecutive lines into citations (each citation starts with "[N]")
            citations = []
            current = []
            for l in ref_lines:
                if re.match(r'^\[\d+\]', l):
                    if current:
                        citations.append(" ".join(current))
                    current = [l]
                elif current:
                    current.append(l)
            if current:
                citations.append(" ".join(current))
            references = " | ".join(citations) if citations else None
        except ValueError:
            pass

        # Fallback name
        if not name:
            name = f"{stat_id} ({collection})" if collection else stat_id

        # --- Note (parenthetical in name) ---
        note = None
        note_match = re.search(r'\(([^)]{5,80})\)\s*\.?\s*$', name)
        if note_match:
            note = note_match.group(1).strip()

        result = {
            "theorem_id": stat_id,
            "name": name.strip(),
            "url": self.PAGE_URL.format(stat_id=stat_id),
        }
        if collection:
            result["collection"] = collection
        if description and description.strip() != name.strip():
            result["description"] = description.strip()
        if note:
            result["note"] = note
        if references:
            result["references"] = references
        if values_str:
            result["values"] = values_str

        return result

    def fetch_statistic(self, stat_id):
        self.stats["attempted"] += 1
        lines = self._fetch_lines(stat_id)
        if lines is None:
            self.stats["not_found"] += 1
            return None
        parsed = self._parse(stat_id, lines)
        if parsed is None:
            self.stats["not_found"] += 1
            return None
        self.seen_ids.add(stat_id)
        self.stats["successful"] += 1
        return parsed

    def run(self, start=1, end=None, limit=None):
        end = end or self.MAX_STAT
        print("\n" + "="*60)
        print("FindStat Ingestor")
        print("="*60)
        print(f"\n[*] Fetching St{start:06d} to St{end:06d}...")

        start_time = time.time()
        consecutive_misses = 0

        for n in range(start, end + 1):
            stat_id = f"St{n:06d}"
            result = self.fetch_statistic(stat_id)

            if result is not None:
                self.parsed_items.append(result)
                consecutive_misses = 0
                if self.stats["successful"] % 50 == 0:
                    print(f"    [{self.stats['successful']}] {stat_id}: {result['name'][:60]}")
            else:
                consecutive_misses += 1
                if consecutive_misses >= 100:
                    print(f"    [*] 100 consecutive misses at {stat_id}, stopping.")
                    break

            if limit and self.stats["successful"] >= limit:
                break

            time.sleep(0.3)

        self._save()
        self._summary(time.time() - start_time)

    def _save(self):
        print("\n[*] Saving...")
        output_file = self.output_dir / "findstat.json"
        lines = ['{\n  "source": "https://www.findstat.org",\n  "statistics": [']
        for i, item in enumerate(self.parsed_items):
            raw = json.dumps(item, indent=4, ensure_ascii=False)
            comma = "," if i < len(self.parsed_items) - 1 else ""
            indented = "\n".join("    " + l for l in raw.splitlines())
            lines.append(indented + comma)
        lines.append("  ]\n}")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"    Saved {len(self.parsed_items)} statistics -> {output_file}")

    def _summary(self, elapsed):
        print("\n" + "="*60)
        print(f"Successful: {self.stats['successful']}")
        print(f"Not found:  {self.stats['not_found']}")
        print(f"Time:       {elapsed/60:.1f} min")
        print("="*60)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", "-o", default="data/findstat")
    p.add_argument("--test", "-t", type=int, default=None)
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--end", type=int, default=None)
    args = p.parse_args()
    FindStatIngestor(args.output).run(start=args.start, end=args.end, limit=args.test)


if __name__ == "__main__":
    main()