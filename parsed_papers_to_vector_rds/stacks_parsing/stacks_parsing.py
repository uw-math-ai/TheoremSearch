from latex_parse import extract
import json
import os

# TODO
#   may need to resolve import paths
#   find the correct files and put their files name in order
#   find a way using tags.csv to generate the url for each theorem
#      in each json, each theorem should theoretically have a label
#      you can use the label to find the tag in the tags file
#      generate the url to the theorem page "https://stacks.math.columbia.edu/tag/{tag_goes_here}"

DIRECTORY = "parsed_papers" # directory to save the jsons
stacks_order = ["introduction.tex", "conventions.tex", "sets.tex", "categories.tex"] # list of filepath strings (in order of the stacks project)
section_num = 1

with open("modified_preamble.tex", "r", encoding="utf-8", errors="ignore") as p:
    preamble = p.read()

for sec in stacks_order:

    with open(sec, "r+", encoding="utf-8", errors="ignore") as s:
        content = s.read()
        content = preamble + content
        s.seek(0)
        s.write(content)
        s.truncate()

    x = extract(sec)

    data = [{"theorem": thm, "body": body, "label": label} for thm, body, label in x]

    for item in data:
        space = item["theorem"].index(" ") + 1
        item["theorem"] = item["theorem"][:space] + f"{str(section_num)}." + item["theorem"][space:]

    output = os.path.join(DIRECTORY, sec)

    with open(output.replace('.tex', '.json'), 'w') as f:
        json.dump(data, f, indent=4) # minor note: '\' gets printed as '\\' in json

    section_num += 1