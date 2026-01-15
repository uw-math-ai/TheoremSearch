#!/usr/bin/env python3
"""
ProofWiki Ingestor
==================
Parses ProofWiki (https://proofwiki.org) via MediaWiki API.

Usage:
    python proofwiki_ingestor.py                    # Full run
    python proofwiki_ingestor.py --test 50          # Test with 50 pages per category
"""

import os
import re
import json
import time
import argparse
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ProofWikiIngestor:
    """ProofWiki ingestor for theorems, lemmas, corollaries, and propositions."""
    
    API_URL = "https://proofwiki.org/w/api.php"
    WIKI_BASE = "https://proofwiki.org/wiki/"
    
    # Categories to parse
    ALL_CATEGORIES = [
        "Proven Results",
        "Theorems",
        "Lemmas",
        "Corollaries", 
        "Propositions",
    ]
    
    # Only keep these types
    ALLOWED_TYPES = {"theorem", "lemma", "corollary", "proposition"}
    
    def __init__(self, output_dir="data/proofwiki"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.parsed_items = []
        self.processed_pages = set()
        self.stats = {
            "total_pages": 0,
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "by_type": {}
        }
        
        self.session = self._create_session()
    
    def _create_session(self):
        """Create requests session with retry logic."""
        session = requests.Session()
        
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        session.headers.update({
            "User-Agent": "MathCopilot/1.0 (Educational research project)"
        })
        
        return session
    
    def get_category_members(self, category, limit=None):
        """Fetch all pages in a category."""
        pages = []
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmlimit": 500,
            "cmtype": "page",
            "format": "json"
        }
        
        while True:
            try:
                r = self.session.get(self.API_URL, params=params, timeout=30)
                r.raise_for_status()
                data = r.json()
                
                if "error" in data:
                    print(f"\n    [!] API Error: {data['error']}")
                    break
                
                if "query" not in data:
                    break
                    
                batch = data["query"].get("categorymembers", [])
                pages.extend(batch)
                
                if limit and len(pages) >= limit:
                    pages = pages[:limit]
                    break
                
                if "continue" in data:
                    params["cmcontinue"] = data["continue"]["cmcontinue"]
                    time.sleep(0.2)
                else:
                    break
                    
            except Exception as e:
                print(f"\n    [!] Error fetching {category}: {e}")
                break
        
        return pages
    
    def get_page_content(self, title):
        """Fetch page content."""
        params = {
            "action": "query",
            "titles": title,
            "prop": "revisions|categories",
            "rvprop": "content",
            "rvslots": "main",
            "cllimit": "max",
            "format": "json"
        }
        
        try:
            r = self.session.get(self.API_URL, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            
            pages = data.get("query", {}).get("pages", {})
            page_id = list(pages.keys())[0]
            
            if page_id == "-1":
                return None
            
            page_data = pages[page_id]
            
            content = None
            try:
                content = page_data["revisions"][0]["slots"]["main"]["*"]
            except (KeyError, IndexError):
                pass
            
            categories = []
            try:
                categories = [c["title"].replace("Category:", "") 
                            for c in page_data.get("categories", [])]
            except:
                pass
            
            return {"content": content, "categories": categories}
            
        except Exception as e:
            return None
    
    def detect_page_type(self, title, content, categories):
        """Determine the type of mathematical content."""
        title_lower = title.lower()
        content_lower = content.lower() if content else ""
        
        type_patterns = [
            ("theorem", ["theorem"]),
            ("lemma", ["lemma"]),
            ("corollary", ["corollary"]),
            ("proposition", ["proposition"]),
        ]
        
        for type_name, patterns in type_patterns:
            for p in patterns:
                if p in title_lower:
                    return type_name
        
        for cat in categories:
            cat_lower = cat.lower()
            if "proven results" in cat_lower:
                return "theorem"
            for type_name, patterns in type_patterns:
                for p in patterns:
                    if p in cat_lower:
                        return type_name
        
        if "== theorem ==" in content_lower:
            return "theorem"
        if "== lemma ==" in content_lower:
            return "lemma"
        
        return "theorem"  # Default for Proven Results
    
    def clean_wikitext(self, text):
        """Convert wikitext to cleaner format."""
        if not text:
            return ""
        
        # Remove MediaWiki tags
        text = re.sub(r'<onlyinclude>', '', text)
        text = re.sub(r'</onlyinclude>', '', text)
        text = re.sub(r'<noinclude>.*?</noinclude>', '', text, flags=re.DOTALL)
        text = re.sub(r'<includeonly>.*?</includeonly>', '', text, flags=re.DOTALL)
        text = re.sub(r'<ref[^>]*>.*?</ref>', '', text, flags=re.DOTALL)
        text = re.sub(r'<ref[^/]*/>', '', text)
        
        # Convert <math> to $...$
        text = re.sub(r'<math>(.*?)</math>', r'$\1$', text, flags=re.DOTALL)
        
        # Handle displaymath
        text = re.sub(r'^:+\s*\$', '$$', text, flags=re.MULTILINE)
        
        # Handle {{eqn}} templates
        def replace_eqn(match):
            content = match.group(1)
            eq_match = re.search(r'\|o\s*=\s*(.*?)(?:\||$)', content)
            if eq_match:
                return f"$${eq_match.group(1).strip()}$$"
            return content
        text = re.sub(r'\{\{eqn\|(.*?)\}\}', replace_eqn, text, flags=re.DOTALL)
        
        # Remove templates
        text = re.sub(r'\{\{DISPLAYTITLE:[^}]+\}\}', '', text)
        text = re.sub(r'\{\{[^{}]*\}\}', '', text)
        
        # Handle wiki links [[Page|display]] -> display
        text = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]+)\]\]', r'\1', text)
        
        # Handle external links
        text = re.sub(r'\[https?://[^\s\]]+ ([^\]]+)\]', r'\1', text)
        text = re.sub(r'\[https?://[^\s\]]+\]', '', text)
        
        # Handle bold/italic
        text = re.sub(r"'''([^']+)'''", r'\1', text)
        text = re.sub(r"''([^']+)''", r'\1', text)
        
        # Clean list markers
        text = re.sub(r'^\*+\s*', '• ', text, flags=re.MULTILINE)
        text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'^:+\s*', '  ', text, flags=re.MULTILINE)
        
        # Clean whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        
        return text.strip()
    
    def parse_wikitext(self, title, raw_content, categories):
        """Parse wikitext into structured format."""
        if not raw_content:
            return None
        
        page_type = self.detect_page_type(title, raw_content, categories)
        
        body = ""
        
        # Try section headers first
        section_patterns = [
            r'==\s*Theorem\s*==\s*\n(.*?)(?=\n==|\Z)',
            r'==\s*Lemma\s*==\s*\n(.*?)(?=\n==|\Z)',
            r'==\s*Corollary\s*==\s*\n(.*?)(?=\n==|\Z)',
            r'==\s*Proposition\s*==\s*\n(.*?)(?=\n==|\Z)',
            r'==\s*Statement\s*==\s*\n(.*?)(?=\n==|\Z)',
            r'==\s*Claim\s*==\s*\n(.*?)(?=\n==|\Z)',
        ]
        
        for pattern in section_patterns:
            match = re.search(pattern, raw_content, re.DOTALL | re.IGNORECASE)
            if match:
                body = self.clean_wikitext(match.group(1))
                break
        
        # Fallback: get content before Proof/Source sections
        if not body:
            content = raw_content
            for marker in ['== Proof', '==Proof', '== Source', '==Source', '== Also see']:
                parts = re.split(re.escape(marker), content, maxsplit=1, flags=re.IGNORECASE)
                if len(parts) > 1:
                    content = parts[0]
                    break
            
            content = re.sub(r'==.*?==\s*\n?', '', content)
            content = re.sub(r'\[\[Category:.*?\]\]', '', content)
            content = re.sub(r'__[A-Z]+__', '', content)
            body = self.clean_wikitext(content)
        
        # Skip if body is too short
        if len(body.strip()) < 20:
            return None
        
        return {
            "theorem_name": title,
            "body": body,
            "type": page_type,
            "url": self.WIKI_BASE + title.replace(" ", "_"),
        }
    
    def process_page(self, title):
        """Process a single page."""
        if title in self.processed_pages:
            return {"status": "skipped", "reason": "duplicate"}
        
        # Skip non-content pages
        if ":" in title and not title.startswith("Definition:"):
            return {"status": "skipped", "reason": "non_content"}
        
        # Skip subpages
        skip_patterns = ["/Proof", "/proof", "/Also known as", "/Historical Note", 
                        "/Source", "/Also see", "/Mistake"]
        for pattern in skip_patterns:
            if pattern in title:
                return {"status": "skipped", "reason": "subpage"}
        
        page_data = self.get_page_content(title)
        if not page_data or not page_data.get("content"):
            return {"status": "failed", "reason": "no_content"}
        
        parsed = self.parse_wikitext(title, page_data["content"], page_data.get("categories", []))
        
        if not parsed:
            return {"status": "failed", "reason": "empty_body"}
        
        if parsed["type"] not in self.ALLOWED_TYPES:
            return {"status": "skipped", "reason": "wrong_type"}
        
        self.parsed_items.append(parsed)
        self.processed_pages.add(title)
        return {"status": "success", "type": parsed["type"]}
    
    def collect_all_pages(self, categories=None, limit_per_category=None):
        """Collect unique pages from all categories."""
        categories = categories or self.ALL_CATEGORIES
        all_pages = {}
        
        print(f"\n[*] Collecting pages from {len(categories)} categories...")
        
        for cat in categories:
            print(f"    Scanning: {cat}...", end=" ", flush=True)
            pages = self.get_category_members(cat, limit=limit_per_category)
            
            new_count = 0
            for page in pages:
                title = page["title"]
                if title not in all_pages:
                    all_pages[title] = cat
                    new_count += 1
            
            print(f"found {len(pages)} ({new_count} new)")
            time.sleep(0.3)
        
        print(f"\n[+] Total unique pages: {len(all_pages)}")
        return all_pages
    
    def run(self, categories=None, limit_per_category=None):
        """Main ingestion loop."""
        print("\n" + "="*60)
        print("ProofWiki Ingestor")
        print("="*60)
        
        all_pages = self.collect_all_pages(categories, limit_per_category)
        
        if not all_pages:
            print("[!] No pages found!")
            return
        
        self.stats["total_pages"] = len(all_pages)
        titles = list(all_pages.keys())
        total = len(titles)
        
        print(f"\n[*] Processing {total} pages...")
        start_time = time.time()
        
        for i, title in enumerate(titles):
            try:
                result = self.process_page(title)
                
                if result["status"] == "success":
                    self.stats["successful"] += 1
                    t = result["type"]
                    self.stats["by_type"][t] = self.stats["by_type"].get(t, 0) + 1
                elif result["status"] == "skipped":
                    self.stats["skipped"] += 1
                else:
                    self.stats["failed"] += 1
                
                if (i + 1) % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = (i + 1) / elapsed
                    eta = (total - i - 1) / rate if rate > 0 else 0
                    print(f"    [{i+1}/{total}] {self.stats['successful']} ok | "
                          f"{rate:.1f}/sec | ETA: {eta/60:.1f} min")
                
                time.sleep(0.25)
                
            except KeyboardInterrupt:
                print("\n[!] Interrupted!")
                break
            except Exception as e:
                self.stats["failed"] += 1
        
        # Save output
        self._save_output()
        self._print_summary(time.time() - start_time)
    
    def _save_output(self):
        """Save all parsed items to JSON."""
        print("\n[*] Saving output...")
        
        output_file = self.output_dir / "proofwiki.json"
        output_data = {
            "source": "https://proofwiki.org",
            "theorems": self.parsed_items
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"    Saved {len(self.parsed_items)} items -> {output_file}")
    
    def _print_summary(self, elapsed):
        """Print final summary."""
        print("\n" + "="*60)
        print("COMPLETE")
        print("="*60)
        print(f"Total pages scanned:  {self.stats['total_pages']}")
        print(f"Successfully parsed:  {self.stats['successful']}")
        print(f"Failed:               {self.stats['failed']}")
        print(f"Skipped:              {self.stats['skipped']}")
        print(f"Time:                 {elapsed/60:.1f} minutes")
        
        print("\n" + "-"*60)
        print("FINAL COUNTS")
        print("-"*60)
        
        key_types = ["theorem", "lemma", "corollary", "proposition"]
        by_type = self.stats.get("by_type", {})
        
        total_key = 0
        for t in key_types:
            count = by_type.get(t, 0)
            total_key += count
            print(f"  {t.upper() + 'S':<20} {count:>6}")
        
        print("-"*60)
        print(f"  {'TOTAL':<20} {total_key:>6}")
        print("="*60)


def main():
    parser = argparse.ArgumentParser(description="Ingest ProofWiki content")
    parser.add_argument("--output", "-o", default="data/proofwiki",
                       help="Output directory")
    parser.add_argument("--test", "-t", type=int, default=None,
                       help="Limit pages per category (for testing)")
    parser.add_argument("--categories", "-c", nargs="+", default=None,
                       help="Specific categories to process")
    
    args = parser.parse_args()
    
    ingestor = ProofWikiIngestor(output_dir=args.output)
    ingestor.run(categories=args.categories, limit_per_category=args.test)


if __name__ == "__main__":
    main()