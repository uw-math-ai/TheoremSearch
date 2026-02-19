#!/usr/bin/env python3
"""
Quick test - fetch known theorem pages directly
"""

import re
import requests
from bs4 import BeautifulSoup

THEOREM_CLASSES = {
    'num_theorem': 'theorem',
    'num_lemma': 'lemma',
    'num_prop': 'proposition',
    'num_cor': 'corollary',
}

# Known pages with theorems (from our earlier debug)
TEST_PAGES = [
    "Yoneda+lemma",
    "adjoint+functor+theorem",
    "Tychonoff+theorem",
    "Stone-Weierstrass+theorem",
    "Hahn-Banach+theorem",
]

def test_fetch():
    print("Testing direct fetch from ncatlab.org\n")
    
    for page in TEST_PAGES:
        url = f"https://ncatlab.org/nlab/show/{page}"
        print(f"--- {page} ---")
        print(f"URL: {url}")
        
        try:
            r = requests.get(url, timeout=30)
            print(f"Status: {r.status_code}")
            
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                
                # Count theorem divs
                for css_class, thm_type in THEOREM_CLASSES.items():
                    divs = soup.find_all('div', class_=css_class)
                    if divs:
                        print(f"  Found {len(divs)} {thm_type}(s) with class '{css_class}'")
                        
                        # Show first one
                        first_div = divs[0]
                        header = first_div.find(['h6', 'strong', 'b'])
                        if header:
                            print(f"    Header: {header.get_text(strip=True)[:50]}")
                        body = first_div.get_text(strip=True)[:100]
                        print(f"    Body: {body}...")
            else:
                print(f"  Failed to fetch!")
                
        except Exception as e:
            print(f"  Error: {e}")
        
        print()

if __name__ == "__main__":
    test_fetch()