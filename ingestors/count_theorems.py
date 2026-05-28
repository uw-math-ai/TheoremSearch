#!/usr/bin/env python3
"""
Theorem Counter
===============
Count theorems across all JSON files in source folders.

Usage:
    python count_theorems.py "C:\path\to\sources"
    python count_theorems.py data/sources
"""

import json
import sys
from pathlib import Path


def count_theorems(base_dir):
    """Count theorems across all JSON files in source folders."""
    base = Path(base_dir)
    
    if not base.exists():
        print(f"[!] Directory not found: {base_dir}")
        return 0
    
    print("\n" + "="*60)
    print("THEOREM COUNT")
    print("="*60)
    
    grand_total = 0
    
    # Check if base_dir contains subfolders or JSON files directly
    has_subfolders = any(p.is_dir() for p in base.iterdir())
    
    if has_subfolders:
        # Process each subfolder
        for folder in sorted(base.iterdir()):
            if not folder.is_dir():
                continue
            
            folder_total = 0
            file_count = 0
            
            for json_file in folder.glob("*.json"):
                count = count_json_file(json_file)
                folder_total += count
                file_count += 1
            
            if folder_total > 0:
                print(f"{folder.name:<40} {folder_total:>6}  ({file_count} files)")
            grand_total += folder_total
    else:
        # Process JSON files directly in base_dir
        for json_file in sorted(base.glob("*.json")):
            count = count_json_file(json_file)
            if count > 0:
                print(f"{json_file.name:<40} {count:>6}")
            grand_total += count
    
    print("="*60)
    print(f"{'TOTAL':<40} {grand_total:>6}")
    print("="*60)
    
    return grand_total


def count_json_file(json_file):
    """Count theorems in a single JSON file."""
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Handle different formats:
        # {"theorems": [...]}
        # {"source": "...", "theorems": [...]}
        # [...]
        if isinstance(data, dict) and "theorems" in data:
            return len(data["theorems"])
        elif isinstance(data, list):
            return len(data)
        else:
            return 0
            
    except Exception as e:
        print(f"  [!] Error reading {json_file.name}: {e}")
        return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python count_theorems.py <path_to_sources>")
        print("Example: python count_theorems.py data/sources")
        sys.exit(1)
    
    path = sys.argv[1]
    count_theorems(path)