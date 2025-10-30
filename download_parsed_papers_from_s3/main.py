import boto3
import os
import tarfile
import json
import shutil
from patterns import *
from tex_files import find_main_tex_file, collect_imports
from latex_parse import extract
from arxiv_metadata import get_paper_metadata

BUCKET_NAME = "arxiv-full-dataset"
S3_PAPERS_DIR = "arxiv_ag_100/"
LOCAL_PARSED_PAPERS_DIR = "parsed_papers"

s3 = boto3.client("s3")

def download_and_parse_papers(
    s3_bucket_name: str = BUCKET_NAME,
    s3_papers_dir: str = S3_PAPERS_DIR,
    local_parsed_papers_dir: str = LOCAL_PARSED_PAPERS_DIR
):
    os.makedirs(local_parsed_papers_dir, exist_ok=True)

    res = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=s3_papers_dir)
    keys = [o["Key"] for o in res.get("Contents", []) if o["Key"].endswith(".tar.gz")]

    for key in keys:
        paper_id = key.replace(".tar.gz", "").split("/")[-1]
        local_paper_path = os.path.join(local_parsed_papers_dir, os.path.basename(key))
        local_parsed_paper_path = os.path.join(local_parsed_papers_dir, os.path.basename(f"{paper_id}_parsed.json"))

        if os.path.exists(local_parsed_paper_path):
            continue
        
        s3.download_file(s3_bucket_name, key, local_paper_path)
        # grab the main tex file

        tar_out = local_paper_path.replace(".tar.gz", "")

        # extract from tar.gz or gzip
        try:
            with tarfile.open(local_paper_path, "r:*") as tar:
                tar.extractall(path=tar_out)
        except:
            with gzip.open(local_parsed_paper_path, "rb") as f_in, open(tar_out, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
                
        file = find_main_tex_file(tar_out)

        if file is None:
            continue
        
        with open(file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            # remove any commented out imports
            content = regex.sub(r"(?<!\\)%.*", "", content)
            content = regex.sub(r'\\begin\{comment\}.*?\\end\{comment\}', '', content, flags=regex.DOTALL)

        import_appends = collect_imports("", tar_out, content, NEWINPUT)
        import_appends = collect_imports(import_appends, tar_out, content, NEWUSEPACKAGE)

        try:
            print(file)
            theorems = extract(file, import_appends)
            # if paper doesn't contain any theorem statements, just skip
            if not theorems:
                print("no theorems found, skipping")
                continue
            
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
                ]
            }

            with open(local_parsed_paper_path, "w", encoding="utf-8") as f:
                json.dump(parsed_paper, f, indent=4)

        except Exception as e:
            print(f"An error occured: {e}")
            print(f"Continuing...")
            continue
        finally:
            # remove folders/tarfiles
            shutil.rmtree(tar_out)
            os.remove(local_paper_path)

if __name__ == "__main__":
    download_and_parse_papers()
