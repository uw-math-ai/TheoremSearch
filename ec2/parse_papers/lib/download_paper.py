from typing import Tuple, Optional
from pathlib import Path
import boto3
import gzip
import tarfile
import io
from ..enums import Mode
import requests

s3 = None

def _get_s3():
    global s3

    if s3 is None:
        s3 = boto3.client("s3")
    
    return s3

def download_paper(
    paper_id: str,
    arxiv_s3_loc: Optional[Tuple[str, int, int]],
    cwd: Path | str,
    mode: Mode,
) -> Path | None:
    """
    Downloads a arXiv paper's source files from S3 or the API.

    Parameters
    ----------
    paper_id : str
        The paper's ID
    arxiv_s3_loc : Optional[Tuple[str, int, int]]
        Name of the bundle, the start bytes, and end bytes. If None, downloads from API
    cwd : Path | str
        Directory's to add the paper's source files to
    mode : Mode
        Mode to run `download_paper_from_s3` in

    Returns
    -------
    paper_dir : Path | None
        The paper's downloaded source files. None if download failed
    """

    if isinstance(cwd, str):
        cwd = Path(cwd)

    safe_paper_id = paper_id.replace("/", "-")
    paper_dir = cwd / safe_paper_id

    # Download the paper's gz from either S3 or the API
    if arxiv_s3_loc is not None:
        bundle_tar, bytes_start, bytes_end = arxiv_s3_loc
        s3 = _get_s3()

        res = s3.get_object(
            Bucket="arxiv",
            Key=bundle_tar,
            Range=f"bytes={bytes_start}-{bytes_end}",
            RequestPayer="requester"
        )

        b = res["Body"].read()
    else:
        res = requests.get(f"https://arxiv.org/src/{paper_id}")
        res.raise_for_status()
        b = res.content
    
    # Extract files
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
    except Exception as e:
        if mode != Mode.PRODUCTION:
            raise RuntimeError(f"Failed to download paper: {e}")
        else:
            return None