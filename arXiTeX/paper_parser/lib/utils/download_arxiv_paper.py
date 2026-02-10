import requests
import gzip
import tarfile
import io
from pathlib import Path
from typing import Optional

def download_arxiv_paper(cwd: Path, arxiv_id: str) -> Optional[Path]:
    """
    Downloads a arXiv paper's source files from S3 or the API.

    Parameters
    ----------
    cwd : Path
        Directory's to add the paper's source files to
    arxiv_id : Optional[str], optional
        arXiv id of a paper. Either this or paper_path must be used.
        
    Returns
    -------
    paper_dir : Optional[Path]
        The paper's downloaded source files. None if download failed
    """
    
    safe_id = arxiv_id.replace("/", "-")

    paper_res = requests.get(f"https://arxiv.org/src/{arxiv_id}")
    paper_res.raise_for_status()

    b = paper_res.content

    paper_dir = cwd / safe_id

    try:
        paper_dir.mkdir(exist_ok=False)
        unzipped = gzip.decompress(b)

        try:
            with tarfile.open(fileobj=io.BytesIO(unzipped), mode="r:*") as tf:
                tf.extractall(path=paper_dir)
        except:
            with open(paper_dir / "main.tex", "wb") as main_file:
                main_file.write(unzipped)

        return paper_dir
    except:
        return None


    
