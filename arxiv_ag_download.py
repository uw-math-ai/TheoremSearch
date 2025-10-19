import arxiv
import os
from pathlib import Path

def make_search(query, start, limit):
    return arxiv.Search(
        query=query,
        max_results=limit,
        start=start
    )

def ag_10_download():
    """
    Downloads the ten most recent Algebraic Geometry papers that were in a journal.
    I chose "Algebra and Number Theory" as the journal, but any journal works as long
    as it has enough publications in math.AG.
    """
    SOURCE_DIR_BASE = "./transfer_folder_ag10"

    os.makedirs(SOURCE_DIR_BASE, exist_ok=True)

    query = "cat:math.AG jr:'Algebra and Number Theory'"
    # "cat:math.AG"
    max_results = 50

    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate
    )

    client = arxiv.Client()

    ctr = 0

    for res in client.results(search):
        if ctr == 10:
            print("ag_10 downloads complete")
            break
        try:
            print(f"Downloading paper's .tar file {ctr}/10")
            paper_id = res.get_short_id().replace('/', '_')
            source_dir = os.path.join(SOURCE_DIR_BASE, f"{paper_id}_source")
            tar_path = res.download_source(dirpath=SOURCE_DIR_BASE, filename=f"{paper_id}.tar.gz")
            ctr += 1
        except:
            print(f"Paper {ctr} .tar not found")

def ag_100_1000_download():
    """
    Downloads the 100 and 1000 most recent articles in Algebraic Geometry from arxiv.
    The papers are downloaded sequentially from the same search to ensure that the two sets
    are disjoint.
    """
    SOURCE_DIR_BASE = ["./transfer_folder_ag100", "./transfer_folder_ag1000"]

    for d in SOURCE_DIR_BASE:
        os.makedirs(d, exist_ok=True)

    query = "cat:math.AG"

    client = arxiv.Client()

    search = arxiv.Search(
        query=query,
        max_results=5000,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    ctr = 0
    dir_idx = 0

    it = client.results(search) # iterator

    while ctr < 1100:
        try:
            res = next(it)
        except arxiv.UnexpectedEmptyPageError:
            print("Empty page from arXiv API — skipping and continuing…")
            continue
        except StopIteration:
            print("No more results available from API.")
            break

        if ctr == 100 and dir_idx == 0:
            dir_idx = 1

        paper_id = res.get_short_id().replace('/', '_')
        filename = f"{paper_id}.tar.gz"
        dirpath = SOURCE_DIR_BASE[dir_idx]

        try:
            print(f"Downloading source [{ctr+1}/1100]: {paper_id}")
            out_path = res.download_source(dirpath=dirpath, filename=filename)

            if not Path(out_path).is_file():
                print(f".tar file missing: {out_path}")
                continue

            ctr += 1

            if ctr in (100, 1000):
                print("ag_100 and 1000 downloads complete")

        except Exception as e:
            print(f"  .tar not found or failed to download for {paper_id}: {e}. Continuing…")
            continue

    print(f"Done. Successfully downloaded {ctr} tarballs.")



if __name__ == "__main__":
    ag_10_download()
    ag_100_1000_download()