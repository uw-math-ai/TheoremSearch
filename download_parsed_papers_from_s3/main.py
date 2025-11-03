import boto3
import os
import tarfile
import json
import shutil
import gzip
from patterns import *
from tex_files import find_main_tex_file, collect_imports
from latex_parse import extract
from arxiv_metadata import get_paper_metadata
import regex

BUCKET_NAME = "arxiv-full-dataset"
S3_PAPERS_DIR = "arxiv_ag_known/"
LOCAL_PARSED_PAPERS_DIR = "parsed_papers"

s3 = boto3.client("s3")

def print_download_progress(download_failures: dict, n: int, N: int):
    failures = len(download_failures)
    successes = n - len(download_failures)

    print(f"{successes} successes, {failures} failures ({n}/{N})")

def download_and_parse_papers(
    s3_bucket_name: str = BUCKET_NAME,
    s3_papers_dir: str = S3_PAPERS_DIR,
    local_parsed_papers_dir: str = LOCAL_PARSED_PAPERS_DIR
):
    os.makedirs(local_parsed_papers_dir, exist_ok=True)

    res = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=s3_papers_dir)
    keys = [o["Key"] for o in res.get("Contents", []) if o["Key"].endswith(".tar.gz")]

    download_failures = {}

    for i, key in enumerate(keys):
        paper_id = key.replace(".tar.gz", "").split("/")[-1].split("_")[-1]
        local_paper_path = os.path.join(local_parsed_papers_dir, os.path.basename(key))
        local_parsed_paper_path = os.path.join(local_parsed_papers_dir, os.path.basename(f"{paper_id}_parsed.json"))

        if os.path.exists(local_parsed_paper_path):
            print_download_progress(download_failures, i + 1, len(keys))
            continue
        
        s3.download_file(s3_bucket_name, key, local_paper_path)
        # grab the main tex file

        tar_out = local_paper_path.replace(".tar.gz", "")

        # extract from tar.gz or gzip
        try:
            with tarfile.open(local_paper_path, "r:*") as tar:
                tar.extractall(path=tar_out)
        except:
            try:
                with gzip.open(local_parsed_paper_path, "rb") as f_in, open(tar_out, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            except Exception as e:
                download_failures[key] = f"{e}"
                
                print_download_progress(download_failures, i + 1, len(keys))
                continue
                
        file = find_main_tex_file(tar_out)

        if file is None:
            download_failures[key] = "No main .tex file found"

            print_download_progress(download_failures, i + 1, len(keys))
            continue
        
        with open(file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            # remove any commented out imports
            content = regex.sub(r"(?<!\\)%.*", "", content)
            content = regex.sub(r'\\begin\{comment\}.*?\\end\{comment\}', '', content, flags=regex.DOTALL)

        import_appends = collect_imports("", tar_out, content, NEWINPUT)
        import_appends = collect_imports(import_appends, tar_out, content, NEWUSEPACKAGE)

        try:
            # print(file)
            theorems = extract(file, import_appends)
            # if paper doesn't contain any theorem statements, just skip
            
            parsed_paper = {
                "theorem_metadata": get_paper_metadata(paper_id),
                "theorem_embeddings": [
                    {
                        "theorem_name": thm,
                        "theorem_slogan": None,
                        "theorem_body": body,
                        "theorem_label": label,
                        "embedding": None
                    }
                    for thm, body, label in theorems
                    if thm.lower().split(" ")[0] in set(["theorem", "proposition", "lemma"])
                ]
            }

            if not parsed_paper["theorem_embeddings"]:
                download_failures[key] = "No theorems, propositions, or lemmas"

                print_download_progress(download_failures, i + 1, len(keys))
                continue

            with open(local_parsed_paper_path, "w", encoding="utf-8") as f:
                json.dump(parsed_paper, f, indent=4)

            print_download_progress(download_failures, i + 1, len(keys))

        except Exception as e:
            download_failures[key] = f"{e}"

            print_download_progress(download_failures, i + 1, len(keys))
            continue
        finally:
            # remove folders/tarfiles
            if os.path.exists(tar_out):
                shutil.rmtree(tar_out)

            if os.path.exists(local_paper_path):
                os.remove(local_paper_path)

    print("\n--- DOWNLOAD FAILURES ---")
    
    for key, e in download_failures.items():
        print(f" > {key}: {e}")

    for f in os.listdir(local_parsed_papers_dir):
        p = os.path.join(local_parsed_papers_dir, f)
        if not (f.endswith("_parsed.json") and os.path.isfile(p)):
            (shutil.rmtree(p) if os.path.isdir(p) else os.remove(p))

if __name__ == "__main__":
    download_and_parse_papers()
