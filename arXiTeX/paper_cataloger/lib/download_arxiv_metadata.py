from pathlib import Path
import requests
from tqdm import tqdm

def download_arxiv_metadata(download_dir: Path):
    download_dir.mkdir(exist_ok=True)

    url = "https://www.kaggle.com/api/v1/datasets/download/Cornell-University/arxiv"
    out_path = download_dir / "arxiv.zip"

    with requests.get(url, stream=True) as r:
        r.raise_for_status()

        total = int(r.headers.get("Content-Length", 0))

        with open(out_path, "wb") as f, tqdm(
            total=total,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc="Downloading arxiv.zip",
            dynamic_ncols=True
        ) as pbar:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                pbar.update(len(chunk))