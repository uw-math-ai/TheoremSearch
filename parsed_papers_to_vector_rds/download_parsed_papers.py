"""
Downloads all or a sample of parsed papers from the 'parsed_papers' directory of the
'arxiv-full-dataset' S3 bucket. Skips download of papers already downloaded.
"""

import boto3
import os
import regex
import tarfile
import glob
import json
import shutil
from patterns import *
from latex_parse import _scanner, extract

BUCKET_NAME = "arxiv-full-dataset" # main folder
S3_PARSED_PAPERS_DIR = "arxiv_ag_100/" # sub folder (add / to prevent extra downloads)
LOCAL_PAPERS_DIR = "parsed_papers" # local folder

s3 = boto3.client("s3")

def find_main_tex_file(source_dir: str):
    """
    Finds the main .tex file in a directory by looking for '\\documentclass'.
    """
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".tex"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        if r"\documentclass" in f.read():
                            print(f"Found main .tex file: {file_path}")
                            return file_path
                except Exception:
                    continue
    return None

def download_parsed_papers(
    n_papers: int | None = None,
    s3_bucket_name: str = BUCKET_NAME,
    s3_parsed_papers_dir: str = S3_PARSED_PAPERS_DIR,
    local_parsed_papers_dir: str = LOCAL_PAPERS_DIR
):
    os.makedirs(local_parsed_papers_dir, exist_ok=True)

    res = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=s3_parsed_papers_dir)
    keys = [o["Key"] for o in res.get("Contents", [])]

    downloaded = 0

    for key in keys:
        if n_papers is not None and downloaded >= n_papers:
            break

        local_parsed_paper_path = os.path.join(local_parsed_papers_dir, os.path.basename(key))

        if os.path.exists(local_parsed_paper_path):
            continue
        else:
            s3.download_file(s3_bucket_name, key, local_parsed_paper_path)
            downloaded += 1
            # grab the main tex file

            tar_out = local_parsed_paper_path.replace(".tar.gz", "")

            with tarfile.open(local_parsed_paper_path, "r:gz") as tar:
                tar.extractall(path=tar_out)
            file = find_main_tex_file(tar_out)

            if file is None:
                continue
            
            with open(file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            import_appends = collect_imports("", tar_out, content, NEWINPUT)
            import_appends = collect_imports(import_appends, tar_out, content, NEWUSEPACKAGE)

            try:
                theorems = extract(file, import_appends)
                data = [{"theorem": thm, "body": body, "label": label} for thm, body, label in theorems]
                # if paper doesn't contain any theorem statements, just skip
                if not data:
                    print("no theorems found, skipping")
                    pass
                else:
                    with open(tar_out + '_theorems.json', 'w') as f:
                        json.dump(data, f, indent=4) # minor note: '\' gets printed as '\\' in json
            except Exception as e:
                print(f"An error occured: {e}")
                print(f"Continuing...")
                continue
            finally:
                # remove folders/tarfiles
                shutil.rmtree(tar_out)
                os.remove(local_parsed_paper_path)


def collect_imports(import_appends: str, tarpath: str, content: str, pattern: str):
    """
    collects any tex that is imported into the main document, can include user-macros, sections, etc.
    """
    paper_imports = _scanner(pattern, content)
    if paper_imports:
        for item in paper_imports:
            if item.group('filepath')[-4:] not in [".tex", ".sty", ".cls"]:
                full_path = os.path.join(tarpath, item.group('filepath')) + ".*"
                file_matches = glob.glob(full_path)
                if file_matches:
                    input_extension = file_matches[0][-4:]
                else:
                    continue
            else:
                input_extension = ""
            with open(os.path.join(tarpath, item.group('filepath')) + input_extension, encoding="utf-8", errors="ignore") as g:
                preamble = g.read()
            import_appends = preamble + import_appends
        return import_appends
    else:
        return import_appends
        
        

if __name__ == "__main__":
    download_parsed_papers(
        n_papers=10,
    )