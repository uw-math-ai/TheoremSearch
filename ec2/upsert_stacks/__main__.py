from ..rds.connect import get_rds_connection
from .sections import get_section_to_tag_map
import zipfile
import json
from tqdm import tqdm

STACKS_PARSED_ZIP_PATH = "ec2/upsert_stacks/data/stacks_parsed.zip"
TAGS_PATH = "ec2/upsert_stacks/data/tags"

conn = get_rds_connection()

def upsert_stacks(
    stack_parsed_zip_path: str = STACKS_PARSED_ZIP_PATH,
    tags_path: str = TAGS_PATH,
    allowed_theorem_types: set[str] = set(["theorem", "proposition", "lemma"]),
):
    section_to_tag = get_section_to_tag_map(tags_path)

    with zipfile.ZipFile(stack_parsed_zip_path, "r") as zp:
        for file_info in tqdm(zp.infolist(), ncols=80):
            if file_info.filename.endswith(".json"):
                theorem_rows = []

                with zp.open(file_info.filename) as f:
                    theorems_json = json.loads(f.read().decode("utf-8"))

                    for theorem in theorems_json:
                        if not theorem["theorem"].split(" ")[0].lower() in allowed_theorem_types:
                            continue

                        theorem_row = (
                            theorem["theorem"],
                            theorem["body"],
                            theorem["label"],
                            theorem["url"]
                        )
                        
                        theorem_rows.append(theorem_row)

                if not theorem_rows:
                    continue

                section = file_info.filename.split("/")[-1].replace(".json", "")
                paper_id = section_to_tag[section]
                paper_authors = ["Aise Johan de Jong"]
                paper_link = f"https://stacks.math.columbia.edu/tag/{paper_id}"
                # TODO: Would be great to directly pull the full title from the .tex
                paper_title = section.replace("-", " ").title()

                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO paper (paper_id, title, authors, link)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (paper_id) DO UPDATE
                        SET
                            title = EXCLUDED.title,
                            authors = EXCLUDED.authors,
                            link = EXCLUDED.link
                    """, (paper_id, paper_title, paper_authors, paper_link))

                    cur.executemany("""
                        INSERT INTO theorem (paper_id, name, body, label, link)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (paper_id, name) DO UPDATE
                        SET
                            body = EXCLUDED.body,
                            label = EXCLUDED.label,
                            link = EXCLUDED.link
                    """, [(paper_id, *theorem_row) for theorem_row in theorem_rows])

                conn.commit()

if __name__ == "__main__":
    upsert_stacks()