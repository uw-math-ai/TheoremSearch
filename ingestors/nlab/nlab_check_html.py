#!/usr/bin/env python3
"""
Debug: Check nlab-content-html repo structure
"""

import requests

GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com/ncatlab/nlab-content-html/master"

def check_html_repo():
    print("Checking nlab-content-html repo...\n")
    
    # Get tree
    api_url = f"{GITHUB_API}/repos/ncatlab/nlab-content-html/git/trees/master?recursive=1"
    
    r = requests.get(api_url, timeout=60)
    data = r.json()
    
    paths = []
    for item in data.get("tree", []):
        path = item.get("path", "")
        if path.endswith(".html"):
            paths.append(path)
    
    print(f"Found {len(paths)} HTML files")
    
    print("\n--- First 10 paths ---")
    for p in paths[:10]:
        print(f"  {p}")
    
    # Fetch one HTML file and look for page title
    if paths:
        print(f"\n--- Checking first HTML file ---")
        test_path = paths[0]
        url = f"{RAW_BASE}/{test_path}"
        print(f"URL: {url}")
        
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            html = r.text
            
            # Look for title
            import re
            title_match = re.search(r'<title>([^<]+)</title>', html)
            if title_match:
                print(f"Title: {title_match.group(1)}")
            
            h1_match = re.search(r'<h1[^>]*id="pageName"[^>]*>([^<]+)</h1>', html)
            if h1_match:
                print(f"Page name (h1): {h1_match.group(1)}")
            
            # Show first 300 chars
            print(f"\nFirst 300 chars:\n{html[:300]}")


if __name__ == "__main__":
    check_html_repo()