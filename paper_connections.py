import csv
import requests
import os
import time
from rds.utils.connect import get_rds_connection

S2_API_KEY = os.getenv("S2_API_KEY")

if not S2_API_KEY:
    raise RuntimeError("S2_API_KEY environment variable not set")

HEADERS = {"x-api-key": S2_API_KEY}

BASE = "https://api.semanticscholar.org/graph/v1"
MIN_INTERVAL = 1.01
last_call = 0.0

def rate_limit(url: str, *, params: dict, headers: dict) -> dict:
    global last_call
    now = time.time()
    dt = now - last_call
    if dt < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - dt)

    r = requests.get(url, params=params, headers=headers, timeout=40)

    last_call = time.time()

    if r.status_code == 429:
        time.sleep(5)
        return rate_limit(url, params=params, headers=headers)

    r.raise_for_status()
    return r.json()

def id_to_url(id: str) -> str:
    return f"URL:https://arxiv.org/abs/{id}"

def fetch_refs(id: str, headers: dict) -> list[str]:
    pid = id_to_url(id)
    url = f"{BASE}/paper/{pid}/references"
    params = {"fields": "citedPaper.externalIds", "limit": 1000, "offset": 0}

    out: list[str] = []
    while True:
        data = rate_limit(url, params=params, headers=headers)
        chunk = data.get("data", [])
        if not chunk:
            break
        for item in chunk:
            ext = (item.get("citedPaper") or {}).get("externalIds") or {}
            ax = ext.get("ArXiv")
            if ax:
                out.append(ax)
        params["offset"] += len(chunk)
        if data.get("total") is not None and params["offset"] >= int(data["total"]):
            break
    return out

def fetch_citing(id: str, headers: dict) -> list[str]:
    pid = id_to_url(id)
    url = f"{BASE}/paper/{pid}/citations"
    params = {"fields": "citingPaper.externalIds", "limit": 1000, "offset": 0}

    out: list[str] = []
    while True:
        data = rate_limit(url, params=params, headers=headers)
        chunk = data.get("data", [])
        if not chunk:
            break
        for item in chunk:
            ext = (item.get("citingPaper") or {}).get("externalIds") or {}
            ax = ext.get("ArXiv")
            if ax:
                out.append(ax)
        params["offset"] += len(chunk)
        if data.get("total") is not None and params["offset"] >= int(data["total"]):
            break
    return out


def insert_rows(rows):
    with get_rds_connection() as conn, conn.cursor() as cur:

        cur.executemany(
            """
            INSERT INTO paper_connections
            (paper_id, ref_papers, citing_papers)
            VALUES (%s,%s,%s)
            ON CONFLICT (paper_id)
            DO UPDATE SET
                ref_papers = EXCLUDED.ref_papers,
                citing_papers = EXCLUDED.citing_papers
            """,
            rows
        )

        conn.commit()


def main():
    arxiv_ids = ['1711.06962v1']

    with open("ag_papers_100.txt", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            arxiv_ids.append(row["paper_id"])

    print("Fetching data for", len(arxiv_ids), "papers")

    rows = []

    for id in arxiv_ids:
        try:
            print(f"Fetching {id}")
            refs = fetch_refs(id, HEADERS)
            cites = fetch_citing(id, HEADERS)

            rows.append((id, refs, cites))

        except requests.HTTPError as e:
            print("Failed:", id, e)

    insert_rows(rows)

    print("Inserted", len(rows), "papers")


if __name__ == "__main__":
    main()