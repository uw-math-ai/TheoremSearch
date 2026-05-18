#!/bin/bash
# Clone formalization projects from projects.json into the canonical location
# expected by the extraction pipelines:
#   <repo>/formalized_graph/data/formalization_projects/<name>/
#
# Usage:
#   clone_projects.sh                       # clone all entries in projects.json
#   clone_projects.sh name1 name2 ...       # clone only the named projects
#
# Idempotent: skips any project whose target dir already exists.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REGISTRY="$REPO_ROOT/formalized_graph/projects.json"
DEST_DIR="$REPO_ROOT/formalized_graph/data/formalization_projects"

mkdir -p "$DEST_DIR"

# Pull a JSON list of {name, url} into bash via python; falls back gracefully
# if a name filter was given on the command line.
mapfile -t ENTRIES < <(python3 - "$REGISTRY" "$@" <<'PY'
import json, sys
registry = json.load(open(sys.argv[1]))
wanted = set(sys.argv[2:])
for entry in registry:
    if wanted and entry["name"] not in wanted:
        continue
    print(f'{entry["name"]}\t{entry["url"]}')
PY
)

if [ "${#ENTRIES[@]}" -eq 0 ]; then
    echo "No projects matched. Available names:"
    python3 -c "import json; [print(' ', e['name']) for e in json.load(open('$REGISTRY'))]"
    exit 1
fi

CLONED=0
SKIPPED=0
FAILED=0

for entry in "${ENTRIES[@]}"; do
    name="${entry%%$'\t'*}"
    url="${entry##*$'\t'}"
    target="$DEST_DIR/$name"
    if [ -d "$target" ]; then
        echo "[skip] $name (already at $target)"
        SKIPPED=$((SKIPPED+1))
        continue
    fi
    echo "[clone] $name <- $url"
    if git clone --depth 1 "$url" "$target" 2>&1 | tail -3; then
        CLONED=$((CLONED+1))
    else
        echo "[FAIL] $name"
        FAILED=$((FAILED+1))
    fi
done

echo
echo "=== summary: cloned=$CLONED skipped=$SKIPPED failed=$FAILED ==="

# Quick module-name hint for each cloned project.
echo
echo "Root .lean files per project (useful for confirming MODULE entries in pipeline scripts):"
for entry in "${ENTRIES[@]}"; do
    name="${entry%%$'\t'*}"
    target="$DEST_DIR/$name"
    [ -d "$target" ] || continue
    roots=$(ls "$target"/*.lean 2>/dev/null | xargs -n1 basename 2>/dev/null | head -3 | tr '\n' ' ')
    printf '  %-32s %s\n' "$name" "${roots:-(no root .lean — check subdirs)}"
done
