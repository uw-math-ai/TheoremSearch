from latex_parse import extract
import json
import os
import csv
from pathlib import Path
# Get the directory where this script file is located
SCRIPT_DIR = Path(__file__).resolve().parent
# Go up two levels to the project root, then find 'stacks_data'
STACKS_DATA_DIR = SCRIPT_DIR / ".." / ".." / "stacks_data"

TAGS_FILE_PATH = STACKS_DATA_DIR / "tags" / "tags"
identifier_to_tag = {}
try:
    with open(TAGS_FILE_PATH, "r", encoding="utf-8") as f:
        # Use csv.reader to handle the comma-separated format
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2:
                tag = row[0]
                identifier = row[1]
                identifier_to_tag[identifier] = tag
    print(f"Successfully loaded {len(identifier_to_tag)} tags.")
except FileNotFoundError:
    print(f"FATAL ERROR: Could not find tags file at {TAGS_FILE_PATH}.")
    print("Please make sure 'stacks_data/tags/tags' exists.")
    exit()  # Exit the script if we can't find the tags
except Exception as e:
    print(f"Error loading tags file: {e}")

# TODO
#   may need to resolve import paths
#   find the correct files and put their files name in order
#   find a way using tags.csv to generate the url for each theorem
#      in each json, each theorem should theoretically have a label
#      you can use the label to find the tag in the tags file
#      generate the url to the theorem page "https://stacks.math.columbia.edu/tag/{tag_goes_here}"



DIRECTORY = "parsed_papers" # directory to save the jsons
# --- REPLACED: Full list of files in order ---
stacks_order = [
    "introduction.tex", "conventions.tex", "sets.tex", "categories.tex", "topology.tex",
    "sheaves.tex", "sites.tex", "stacks.tex", "fields.tex", "algebra.tex", "brauer.tex",
    "homology.tex", "derived.tex", "simplicial.tex", "more-algebra.tex", "smoothing.tex",
    "modules.tex", "sites-modules.tex", "injectives.tex", "cohomology.tex",
    "sites-cohomology.tex", "dga.tex", "dpa.tex", "sdga.tex", "hypercovering.tex",
    "schemes.tex", "constructions.tex", "properties.tex", "morphisms.tex", "coherent.tex",
    "divisors.tex", "limits.tex", "varieties.tex", "topologies.tex", "descent.tex",
    "perfect.tex", "more-morphisms.tex", "flat.tex", "groupoids.tex", "more-groupoids.tex",
    "etale.tex", "chow.tex", "intersection.tex", "pic.tex", "weil.tex", "adequate.tex",
    "dualizing.tex", "duality.tex", "discriminant.tex", "derham.tex", "local-cohomology.tex",
    "algebraization.tex", "curves.tex", "resolve.tex", "models.tex", "functors.tex",
    "equiv.tex", "pione.tex", "etale-cohomology.tex", "proetale.tex", "relative-cycles.tex",
    "more-etale.tex", "trace.tex", "crystalline.tex", "spaces.tex", "spaces-properties.tex",
    "spaces-morphisms.tex", "decent-spaces.tex", "spaces-cohomology.tex", "spaces-limits.tex",
    "spaces-divisors.tex", "spaces-over-fields.tex", "spaces-topologies.tex",
    "spaces-descent.tex", "spaces-perfect.tex", "spaces-more-morphisms.tex",
    "spaces-flat.tex", "spaces-groupoids.tex", "spaces-more-groupoids.tex",
    "bootstrap.tex", "spaces-pushouts.tex", "spaces-chow.tex", "groupoids-quotients.tex",
    "spaces-more-cohomology.tex", "spaces-simplicial.tex", "spaces-duality.tex",
    "formal-spaces.tex", "restricted.tex", "spaces-resolve.tex", "formal-defos.tex",
    "defos.tex", "cotangent.tex", "examples-defos.tex", "algebraic.tex",
    "examples-stacks.tex", "stacks-sheaves.tex", "criteria.tex", "artin.tex", "quot.tex",
    "stacks-properties.tex", "stacks-morphisms.tex", "stacks-limits.tex",
    "stacks-cohomology.tex", "stacks-perfect.tex", "stacks-introduction.tex",
    "stacks-more-morphisms.tex", "stacks-geometry.tex", "moduli.tex", "moduli-curves.tex",
    "examples.tex", "exercises.tex", "guide.tex", "desirables.tex", "coding.tex",
    "obsolete.tex"
]
section_num = 1

PREAMBLE_PATH = SCRIPT_DIR / "modified_preamble.tex"
with open(PREAMBLE_PATH, "r", encoding="utf-8", errors="ignore") as p:
    preamble = p.read()

if not os.path.exists(DIRECTORY):
    os.makedirs(DIRECTORY)

for sec_filename in stacks_order:
    
    # 1. Resolve the path to the file in stacks_data
    source_tex_path = STACKS_DATA_DIR / sec_filename

    if not source_tex_path.exists():
        print(f"File not found, skipping: {source_tex_path}")
        continue

    # 2. Modify the file in stacks_data to include the preamble
    try:
        with open(source_tex_path, "r+", encoding="utf-8", errors="ignore") as s:
            content = s.read()
            # Check if preamble is already there to avoid prepending multiple times
            if not content.startswith(preamble):
                s.seek(0)
                s.write(preamble + content)
                s.truncate()
    except Exception as e:
        print(f"Error modifying {source_tex_path}: {e}")
        continue
    
    # 3. Extract from the modified file
    try:
        # Pass the path as a string to extract
        extracted_data = extract(str(source_tex_path))
    except Exception as e:
        print(f"Error parsing {source_tex_path} with latex_parse: {e}")
        continue

    data = []
    filename_base = sec_filename.replace('.tex', '')

    # 4. Process each theorem and ADD THE URL
    for thm, body, label in extracted_data:
        # Construct the identifier (e.g., "algebra-lemma-finite-type")
        identifier = f"{filename_base}-{label}"
        
        # Look up the tag from our dictionary
        tag = identifier_to_tag.get(identifier)
        
        # Generate the URL
        url = f"https://stacks.math.columbia.edu/tag/{tag}" if tag else None

        # Add section number (as in original script)
        space = thm.index(" ") + 1
        theorem_name = thm[:space] + f"{str(section_num)}." + thm[space:]

        # Append all new data to our list
        data.append({
            "theorem": theorem_name,
            "body": body,
            "label": label,
            "tag": tag,          # <-- This is new
            "url": url,          # <-- This is new
            "source_filename": sec_filename
        })

    # 5. Save the JSON output
    output_json_path = os.path.join(DIRECTORY, f"{filename_base}.json")
    with open(output_json_path, 'w') as f:
        json.dump(data, f, indent=4)

    print(f"Successfully parsed {sec_filename} -> {output_json_path}")
    section_num += 1

print("All files parsed.")