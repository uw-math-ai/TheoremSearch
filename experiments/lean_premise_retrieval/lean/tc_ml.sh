#!/bin/bash
# Typecheck a candidate Mathlib statement against v4.30 Mathlib.
# Usage: tc_ml.sh 'theorem cand <binders> : <type> := sorry'
# Submit fully-qualified names (e.g. CategoryTheory.Limits...); no `open` is set.
cand="$*"
if printf '%s' "$cand" | grep -qE '#check|#print|#eval|#synth|import |sorryAx'; then
  echo "REJECTED: no #check/#print/#eval/import; submit 'theorem cand ... := sorry'"; exit 1
fi
f=$(mktemp /tmp/mlcand.XXXXXX.lean)
{ echo 'import Mathlib'; echo ''; printf '%s\n' "$cand"; } > "$f"
# MATHLIB_PROJECT must point at a built lake project where `import Mathlib` resolves (v4.30).
MATHLIB_PROJECT="${MATHLIB_PROJECT:-/home/aurasl/projects/lean-repos/brownian-motion-v430-rc2}"
cd "$MATHLIB_PROJECT" && timeout 300 lake env lean "$f" 2>&1 | grep -iE 'error|sorry' | head -25
echo "---END---"
rm -f "$f"
