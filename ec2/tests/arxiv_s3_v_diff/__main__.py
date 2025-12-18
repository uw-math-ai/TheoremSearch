"""
Samples N random math papers in the arXiv S3 bucket and estimates the probability of a version
mismatch.
"""

from argparse import ArgumentParser
from ...parse_arxiv_papers.download_and_extract_paper import download_and_extract_paper, extract_paper_src
from ...rds.connect import get_rds_connection
from tempfile import TemporaryDirectory
import requests
import os
import filecmp
from tqdm import tqdm

def _download_and_extract_paper_from_api(paper_id: str, cwd: str):
    url = f"https://arxiv.org/src/{paper_id}"
    src_gz_path = src_gz_path = os.path.join(cwd, f"{paper_id.replace('/', '-')}_api.gz")
    src_dir = src_gz_path.removesuffix(".gz")

    with requests.get(url, stream=True) as res:
        res.raise_for_status()

        with open(src_gz_path, "wb") as src_gz_b:
            for chunk in res.iter_content(chunk_size=8192):
                src_gz_b.write(chunk)

    extract_paper_src(src_gz_path, src_dir)

    return src_dir

def _dirs_are_equal(dir1: str, dir2: str):
    comparison = filecmp.dircmp(dir1, dir2)

    if comparison.left_only or comparison.right_only or comparison.diff_files:
        return False
    
    for subdir in comparison.common_dirs:
        subdir1 = os.path.join(dir1, subdir)
        subdir2 = os.path.join(dir2, subdir)
        
        if not _dirs_are_equal(subdir1, subdir2):
            return False
            
    return True

def estimate_arxiv_s3_v_diff(N: int):
    diffs = 0.0
    trials = 0

    conn = get_rds_connection()

    with conn.cursor() as cur:
        cur.execute("""
            SELECT paper.paper_id, paper_loc.bundle_tar, paper_loc.bytes_start, paper_loc.bytes_end FROM paper
            INNER JOIN paper_arxiv_s3_location paper_loc ON paper_loc.paper_id = paper.paper_id
            ORDER BY RANDOM()
            LIMIT %s
        """, (N,))

        rows = cur.fetchall()

    for paper_id, *paper_s3_loc in tqdm(rows, dynamic_ncols=True):
        with TemporaryDirectory() as paper_dir:
            src_dir_s3 = download_and_extract_paper(paper_id, paper_s3_loc, paper_dir)
            src_dir_api = _download_and_extract_paper_from_api(paper_id, paper_dir)

            if src_dir_s3 and src_dir_api:
                trials += 1

                if not _dirs_are_equal(src_dir_s3, src_dir_api):
                    diffs += 1.0

    p_hat = diffs / trials
    std = (p_hat*(1-p_hat)/trials)**0.5

    return p_hat, std, trials

if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "--N",
        type=int,
        required=False,
        default=1000
    )

    args = arg_parser.parse_args()

    p_hat, std_hat, trials = estimate_arxiv_s3_v_diff(N=args.N)

    ci_low  = p_hat - 1.96 * std_hat
    ci_high = p_hat + 1.96 * std_hat

    print("\n=== arXiv S3 Version Mismatch Estimate ===")
    print(f"Sample size (N): {trials}")
    print(f"Estimated proportion (p̂): {p_hat:.4f}")
    print(f"Std. error: {std_hat:.4f}")
    print(f"95% CI: [{ci_low:.4f}, {ci_high:.4f}]\n")