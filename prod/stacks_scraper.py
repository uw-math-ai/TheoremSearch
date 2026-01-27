import csv
import requests
from bs4 import BeautifulSoup
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

URL = "https://stacks.math.columbia.edu/recent-comments"
OUTPUT_CSV = "stacks_recent_comments.csv"
SLOGAN_KEYWORDS = [
    "slogan"
]

def make_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "StacksCommentParser/1.0 (academic research; contact if needed)"
    })

    retries = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"]
    )

    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session

def looks_like_slogan(text):
    t = text.lower()
    return any(k in t for k in SLOGAN_KEYWORDS)

def fetch_comments():
    session = make_session()

    # (connect timeout, read timeout)
    r = session.get(URL, timeout=(10, 60))
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    rows = []

    for div in soup.find_all("div", class_="comment"):
        text = div.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text)

        tag = None
        for a in div.find_all("a", href=True):
            if "/tag/" in a["href"]:
                tag = a["href"].split("/tag/")[-1]
                break

        if tag and text and looks_like_slogan(text):
            rows.append({
                "tag": tag,
                "comment": text
            })

    return rows

def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["tag", "comment"])
        writer.writeheader()
        writer.writerows(rows)

def main():
    rows = fetch_comments()
    write_csv(rows, OUTPUT_CSV)
    print(f"Wrote {len(rows)} comments to {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
