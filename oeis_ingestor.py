#!/usr/bin/env python3
"""
OEIS Ingestor
=============
Fetches sequences from the On-Line Encyclopedia of Integer Sequences (OEIS).

Output format:
{
    "sequence_id": "A000045",
    "name": "Fibonacci numbers",
    "values": [0, 1, 1, 2, 3, 5, 8, 13, ...],
    "offset": "0,3",
    "formula": "...",
    "comment": "...",
    "example": "...",
    "note": "...",
    "url": "https://oeis.org/A000045"
}

Usage:
    python oeis_ingestor.py                        # Full run
    python oeis_ingestor.py --test 100             # Test with 100 sequences
    python oeis_ingestor.py --keyword core nice    # Specific keywords
"""

import re
import json
import time
import argparse
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class OEISIngestor:
    """OEIS ingestor - fetches sequences via the OEIS JSON API."""

    API_URL = "https://oeis.org/search"
    OEIS_BASE = "https://oeis.org"

    # OEIS keyword groups to sweep for broad coverage
    DEFAULT_KEYWORDS = [
        "core",
        "nice",
        "easy",
        "hard",
        "eigen",
        "walk",
        "frac",
        "mult",
        "cons",
    ]

    def __init__(self, output_dir="data/oeis"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.parsed_items = []
        self.seen_ids = set()
        self.stats = {
            "total_fetched": 0,
            "successful": 0,
            "skipped": 0,
            "failed": 0,
        }

        self.session = self._create_session()

    def _create_session(self):
        session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({"User-Agent": "MathCopilot/1.0 (Educational research)"})
        return session

    def search(self, query, start=0, count=25):
        """
        Call OEIS search API.
        The API returns a raw JSON array of sequence objects.
        Returns empty list on failure or no results.
        """
        params = {
            "q": query,
            "fmt": "json",
            "start": start,
            "n": count,
        }
        try:
            r = self.session.get(self.API_URL, params=params, timeout=30)
            r.raise_for_status()
            # OEIS returns empty body (not "[]") when past end of results
            if not r.text.strip():
                return []
            data = r.json()
            # API returns a list directly
            if isinstance(data, list):
                return data
            # Some responses may still wrap in a dict
            if isinstance(data, dict):
                return data.get("results") or []
            return []
        except json.JSONDecodeError:
            # Empty or malformed response means no more results
            return []
        except Exception as e:
            print(f"    [!] Search error (query={query}, start={start}): {e}")
            return []

    def _join_field(self, raw, field):
        """
        OEIS fields like comment, formula, example are lists of strings.
        Join them into one clean string, stripping author tags like _AuthorName_.
        """
        entries = raw.get(field, [])
        if not entries:
            return None
        cleaned = []
        for entry in entries:
            entry = re.sub(r'^_[^_]+_\s*', '', str(entry)).strip()
            if entry:
                cleaned.append(entry)
        return " | ".join(cleaned) if cleaned else None

    def parse_sequence(self, raw):
        """
        Parse a raw OEIS API result into a structured dict.
        Returns None if the sequence should be skipped.
        """
        number = raw.get("number")
        if number is None:
            return None

        sequence_id = f"A{str(number).zfill(6)}"

        if sequence_id in self.seen_ids:
            return None

        name = raw.get("name", "").strip()
        if not name:
            return None

        # Values from comma-separated "data" field
        values = []
        raw_data = raw.get("data", "")
        if raw_data:
            try:
                values = [int(x.strip()) for x in str(raw_data).split(",") if x.strip()]
            except ValueError:
                values = []

        # Offset — e.g. "0,3" means sequence starts at index 0
        offset = raw.get("offset", "")
        if isinstance(offset, str):
            offset = offset.strip() or None

        # Optional descriptive fields
        formula = self._join_field(raw, "formula")
        comment = self._join_field(raw, "comment")
        example = self._join_field(raw, "example")

        # Note — parenthetical at end of name
        note = None
        note_match = re.search(r'\(([^)]+)\)\s*\.?\s*$', name)
        if note_match:
            note = note_match.group(1).strip()

        result = {
            "sequence_id": sequence_id,
            "name": name,
            "values": values,
            "url": f"{self.OEIS_BASE}/{sequence_id}",
        }

        # Optional fields only added if present
        if offset:
            result["offset"] = offset
        if note:
            result["note"] = note
        if formula:
            result["formula"] = formula
        if comment:
            result["comment"] = comment
        if example:
            result["example"] = example

        return result

    def fetch_all_for_query(self, query, limit=None):
        """
        Page through all results for a given query.
        Stops when the API returns an empty batch or limit is reached.
        """
        count = 0
        start = 0
        page_size = 25

        while True:
            batch = self.search(query, start=start, count=page_size)

            # Empty batch means no more results
            if not batch:
                break

            self.stats["total_fetched"] += len(batch)

            for raw in batch:
                parsed = self.parse_sequence(raw)
                if parsed is None:
                    self.stats["skipped"] += 1
                    continue

                self.parsed_items.append(parsed)
                self.seen_ids.add(parsed["sequence_id"])
                self.stats["successful"] += 1
                count += 1

                if limit and self.stats["successful"] >= limit:
                    return count

            # If batch was smaller than page_size we've hit the end
            if len(batch) < page_size:
                break

            start += page_size
            time.sleep(0.5)  # Be respectful to OEIS servers

        return count

    def run(self, keywords=None, limit=None):
        """Main ingestion loop."""
        print("\n" + "="*60)
        print("OEIS Ingestor")
        print("="*60)

        keywords = keywords or self.DEFAULT_KEYWORDS
        start_time = time.time()

        print(f"\n[*] Fetching sequences across {len(keywords)} keyword groups...")

        for kw in keywords:
            query = f"keyword:{kw}"
            print(f"    Scanning '{kw}'...", end=" ", flush=True)
            fetched = self.fetch_all_for_query(query, limit=limit)
            print(f"{fetched} new sequences")

            if limit and self.stats["successful"] >= limit:
                break

        self._save_output()
        self._print_summary(time.time() - start_time)

    def _save_output(self):
        print("\n[*] Saving output...")
        output_file = self.output_dir / "oeis.json"

        # Custom serialization: pretty-print the outer structure but keep
        # "values" arrays compact on a single line.
        lines = ['{\n  "source": "https://oeis.org",\n  "sequences": [']
        for i, seq in enumerate(self.parsed_items):
            # Serialize the sequence dict with indent, then replace the
            # expanded "values" array with a compact inline version.
            raw = json.dumps(seq, indent=4, ensure_ascii=False)
            # Compact the values list: replace the multiline array with one line
            raw = re.sub(
                r'"values": \[\n\s*([\s\S]*?)\n\s*\]',
                lambda m: '"values": [' + ', '.join(
                    v.strip().rstrip(',') for v in m.group(1).split('\n') if v.strip()
                ) + ']',
                raw
            )
            comma = "," if i < len(self.parsed_items) - 1 else ""
            # Indent the whole sequence block by 4 spaces
            indented = "\n".join("    " + line for line in raw.splitlines())
            lines.append(indented + comma)
        lines.append("  ]\n}")

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
        print(f"    Saved {len(self.parsed_items)} sequences -> {output_file}")

    def _print_summary(self, elapsed):
        print("\n" + "="*60)
        print("COMPLETE")
        print("="*60)
        print(f"Total API results:    {self.stats['total_fetched']}")
        print(f"Successfully parsed:  {self.stats['successful']}")
        print(f"Skipped (duplicate):  {self.stats['skipped']}")
        print(f"Failed:               {self.stats['failed']}")
        print(f"Time:                 {elapsed/60:.1f} minutes")
        print("="*60)


def main():
    parser = argparse.ArgumentParser(description="Ingest OEIS sequences")
    parser.add_argument("--output", "-o", default="data/oeis", help="Output directory")
    parser.add_argument("--test", "-t", type=int, default=None,
                        help="Limit total sequences (for testing)")
    parser.add_argument("--keyword", "-k", nargs="+", default=None,
                        help="OEIS keywords to search (e.g. core nice easy)")

    args = parser.parse_args()

    ingestor = OEISIngestor(output_dir=args.output)
    ingestor.run(keywords=args.keyword, limit=args.test)


if __name__ == "__main__":
    main()