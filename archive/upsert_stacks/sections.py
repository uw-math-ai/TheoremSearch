def get_section_to_tag_map(tags_path: str):
    section_to_tag = {}

    with open(tags_path, "r") as f:
        for line in f.readlines():
            if line.strip().endswith("-section-phantom"):
                contents = line.split(",")

                tag = contents[0]
                section = contents[1].replace("-section-phantom", "").strip()

                section_to_tag[section] = tag

    return section_to_tag