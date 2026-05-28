#!/usr/bin/env python3
"""
ProofWiki Data Analyzer
=======================
Analyze and verify ingested ProofWiki data.
"""

import os
import json
from pathlib import Path
from collections import Counter
import argparse


def analyze_output(data_dir="data/proofwiki"):
    """Analyze the ingested ProofWiki data."""
    data_dir = Path(data_dir)
    pages_dir = data_dir / "pages"
    
    if not pages_dir.exists():
        print(f"[!] No data found in {data_dir}")
        return
    
    # Collect stats
    type_counts = Counter()
    category_counts = Counter()
    has_proof = 0
    has_statement = 0
    latex_blocks = 0
    total_pages = 0
    
    print(f"[*] Analyzing data in {data_dir}...")
    
    for json_file in pages_dir.glob("*.json"):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                item = json.load(f)
            
            total_pages += 1
            type_counts[item.get("type", "unknown")] += 1
            
            for cat in item.get("categories", []):
                category_counts[cat] += 1
            
            if item.get("proof"):
                has_proof += 1
            if item.get("statement"):
                has_statement += 1
            
            latex_blocks += len(item.get("raw_latex", []))
            
        except Exception as e:
            print(f"  [!] Error reading {json_file.name}: {e}")
    
    # Print report
    print("\n" + "="*60)
    print("PROOFWIKI DATA ANALYSIS")
    print("="*60)
    
    print(f"\nTotal pages: {total_pages}")
    print(f"With statement: {has_statement} ({100*has_statement/total_pages:.1f}%)")
    print(f"With proof: {has_proof} ({100*has_proof/total_pages:.1f}%)")
    print(f"Total LaTeX blocks: {latex_blocks}")
    
    print(f"\n--- By Type ---")
    for type_name, count in type_counts.most_common(20):
        print(f"  {type_name}: {count}")
    
    print(f"\n--- Top Categories ---")
    for cat, count in category_counts.most_common(30):
        print(f"  {cat}: {count}")
    
    return {
        "total": total_pages,
        "by_type": dict(type_counts),
        "top_categories": dict(category_counts.most_common(50))
    }


def sample_pages(data_dir="data/proofwiki", page_type=None, n=5):
    """Show sample parsed pages."""
    data_dir = Path(data_dir)
    pages_dir = data_dir / "pages"
    
    count = 0
    for json_file in pages_dir.glob("*.json"):
        if count >= n:
            break
            
        with open(json_file, 'r', encoding='utf-8') as f:
            item = json.load(f)
        
        if page_type and item.get("type") != page_type:
            continue
        
        print("\n" + "="*60)
        print(f"Title: {item['title']}")
        print(f"Type: {item['type']}")
        print(f"URL: {item['url']}")
        print(f"Categories: {', '.join(item.get('categories', [])[:5])}")
        print("-"*60)
        print("Statement:")
        print(item.get("statement", "(none)")[:500])
        if item.get("proof"):
            print("-"*60)
            print("Proof (truncated):")
            print(item["proof"][:300] + "...")
        print("="*60)
        
        count += 1


def export_for_embedding(data_dir="data/proofwiki", output_file=None):
    """Export data in format suitable for vector embedding."""
    data_dir = Path(data_dir)
    pages_dir = data_dir / "pages"
    output_file = output_file or data_dir / "embedding_ready.jsonl"
    
    print(f"[*] Exporting for embedding...")
    
    count = 0
    with open(output_file, 'w', encoding='utf-8') as f:
        for json_file in pages_dir.glob("*.json"):
            with open(json_file, 'r', encoding='utf-8') as jf:
                item = json.load(jf)
            
            # Create embedding-ready record
            text_parts = []
            if item.get("statement"):
                text_parts.append(item["statement"])
            if item.get("proof"):
                text_parts.append(f"Proof: {item['proof']}")
            
            if not text_parts:
                continue
            
            record = {
                "id": item.get("pageid") or json_file.stem,
                "title": item["title"],
                "type": item["type"],
                "url": item["url"],
                "text": "\n\n".join(text_parts),
                "categories": item.get("categories", []),
            }
            
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    
    print(f"[+] Exported {count} records to {output_file}")
    return output_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze ProofWiki data")
    parser.add_argument("command", choices=["analyze", "sample", "export"],
                       help="Command to run")
    parser.add_argument("--dir", "-d", default="data/proofwiki",
                       help="Data directory")
    parser.add_argument("--type", "-t", default=None,
                       help="Filter by type (for sample)")
    parser.add_argument("--count", "-n", type=int, default=5,
                       help="Number of samples")
    
    args = parser.parse_args()
    
    if args.command == "analyze":
        analyze_output(args.dir)
    elif args.command == "sample":
        sample_pages(args.dir, args.type, args.count)
    elif args.command == "export":
        export_for_embedding(args.dir)
