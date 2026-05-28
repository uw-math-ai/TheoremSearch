#!/usr/bin/env python3
"""
OEIS Ingestor
=============
Fetches sequences from the On-Line Encyclopedia of Integer Sequences (OEIS)
by iterating A-numbers directly (A000001 through ~A393135).

The OEIS JSON API endpoint:
    https://oeis.org/search?q=id:A000045&fmt=json

Output format:
{
    "sequence_id": "A000045",
    "name": "Fibonacci numbers",
    "values": [0, 1, 1, 2, 3, 5, 8, ...],
    "offset": "0,3",
    "formula": "...",
    "comment": "...",
    "example": "...",
    "note": "...",
    "url": "https://oeis.org/A000045"
}

Usage:
    python oeis_ingestor.py                  # Full run (A000001 to A393200)
    python oeis_ingestor.py --test 100       # First 100 sequences
    python oeis_ingestor.py --start 1000 --end 5000
    python oeis_ingestor.py --batch 50       # Fetch 50 IDs per API call (faster)
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
    """OEIS ingestor - iterates A-numbers and fetches via the OEIS JSON API."""

    API_URL = "https://oeis.org/search"
    OEIS_BASE = "https://oeis.org"
    MAX_SEQUENCE = 393200   # Current OEIS size, update as needed

    def __init__(self, output_dir="data/oeis"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.parsed_items = []
        self.seen_ids = set()
        self.stats = {
            "total_fetched": 0,
            "successful": 0,
            "not_found": 0,
            "failed": 0,
        }

        self.session = self._create_session()

    def _create_session(self):
        session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers["User-Agent"] = "MathCopilot/1.0 (Educational research)"
        return session

    def fetch_batch(self, ids):
        """
        Fetch a batch of sequences by A-number in one API call.
        OEIS supports OR queries: id:A000001|id:A000002|...
        Returns list of raw sequence dicts.
        """
        query = "|".join(f"id:{seq_id}" for seq_id in ids)
        params = {"q": query, "fmt": "json", "n": len(ids)}
        try:
            r = self.session.get(self.API_URL, params=params, timeout=30)
            r.raise_for_status()
            if not r.text.strip():
                return []
            data = r.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("results") or []
            return []
        except json.JSONDecodeError:
            return []
        except Exception as e:
            print(f"    [!] Fetch error for batch starting {ids[0]}: {e}")
            return []

    def _join_field(self, raw, field):
        """Join a list-of-strings OEIS field, stripping _AuthorName_ tags."""
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
        Returns None if the sequence is invalid or already seen.
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

        values = []
        raw_data = raw.get("data", "")
        if raw_data:
            try:
                values = [int(x.strip()) for x in str(raw_data).split(",") if x.strip()]
            except ValueError:
                values = []

        offset = raw.get("offset", "")
        if isinstance(offset, str):
            offset = offset.strip() or None

        formula = self._join_field(raw, "formula")
        comment = self._join_field(raw, "comment")
        example = self._join_field(raw, "example")

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

    def run(self, start=1, end=None, limit=None, batch_size=20):
        """
        Iterate A-numbers from start to end, fetching in batches.
        """
        end = end or self.MAX_SEQUENCE
        print("\n" + "="*60)
        print("OEIS Ingestor")
        print("="*60)
        print(f"\n[*] Fetching A{start:06d} to A{end:06d} (batch size {batch_size})...")
        start_time = time.time()

        n = start
        while n <= end:
            batch_ids = [f"A{i:06d}" for i in range(n, min(n + batch_size, end + 1))]
            results = self.fetch_batch(batch_ids)
            self.stats["total_fetched"] += len(results)

            returned_ids = set()
            for raw in results:
                number = raw.get("number")
                if number is not None:
                    returned_ids.add(f"A{str(number).zfill(6)}")
                parsed = self.parse_sequence(raw)
                if parsed is None:
                    continue
                self.parsed_items.append(parsed)
                self.seen_ids.add(parsed["sequence_id"])
                self.stats["successful"] += 1

            missing = len(batch_ids) - len(returned_ids)
            self.stats["not_found"] += missing

            if self.stats["successful"] % 500 == 0 and self.stats["successful"] > 0:
                elapsed = time.time() - start_time
                rate = self.stats["successful"] / elapsed * 60
                print(f"    [{self.stats['successful']:,}] A{n:06d} | {rate:.0f}/min")

            if limit and self.stats["successful"] >= limit:
                break

            # Checkpoint save every 10k sequences
            if self.stats["successful"] > 0 and self.stats["successful"] % 10000 == 0:
                self._save_output(checkpoint=True)

            n += batch_size
            time.sleep(0.5)

        self._save_output()
        self._print_summary(time.time() - start_time)

    def _save_output(self, checkpoint=False):
        suffix = f"_checkpoint_{self.stats['successful']}" if checkpoint else ""
        output_file = self.output_dir / f"oeis{suffix}.json"
        print(f"\n[*] Saving {len(self.parsed_items):,} sequences -> {output_file}")

        lines = ['{\n  "source": "https://oeis.org",\n  "sequences": [']
        for i, seq in enumerate(self.parsed_items):
            raw = json.dumps(seq, indent=4, ensure_ascii=False)
            raw = re.sub(
                r'"values": \[\n\s*([\s\S]*?)\n\s*\]',
                lambda m: '"values": [' + ', '.join(
                    v.strip().rstrip(',') for v in m.group(1).split('\n') if v.strip()
                ) + ']',
                raw
            )
            comma = "," if i < len(self.parsed_items) - 1 else ""
            indented = "\n".join("    " + line for line in raw.splitlines())
            lines.append(indented + comma)
        lines.append("  ]\n}")

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))

    def _print_summary(self, elapsed):
        print("\n" + "="*60)
        print("COMPLETE")
        print("="*60)
        print(f"Successfully parsed:  {self.stats['successful']:,}")
        print(f"Not found/skipped:    {self.stats['not_found']:,}")
        print(f"Time:                 {elapsed/60:.1f} minutes")
        print("="*60)


def main():
    parser = argparse.ArgumentParser(description="Ingest OEIS sequences by A-number")
    parser.add_argument("--output", "-o", default="data/oeis")
    parser.add_argument("--test", "-t", type=int, default=None,
                        help="Stop after N sequences (for testing)")
    parser.add_argument("--start", type=int, default=1,
                        help="Starting A-number (default: 1)")
    parser.add_argument("--end", type=int, default=None,
                        help="Ending A-number (default: 393200)")
    parser.add_argument("--batch", type=int, default=20,
                        help="IDs per API call (default: 20, max ~50)")

    args = parser.parse_args()
    OEISIngestor(args.output).run(
        start=args.start,
        end=args.end,
        limit=args.test,
        batch_size=args.batch,
    )


if __name__ == "__main__":
    main()