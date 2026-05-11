# Slogan pilot (apap)

FL-side slogan generation for the 38 apap blueprint decls. NL-side controls
(LaTeX statement bodies, teammate-curated) are joined by `\lean{decl_name}`.

## Files

- `PROMPT.md` — kickoff prompt (style rules + worked examples).
- `decls.txt` — the 38 decl names extracted from apap blueprint `\lean{}` tags.
- `pilot.py` — harness: resolves names in `corpus_v2_mathlib_plus_v4.29.db`,
  pulls blueprint LaTeX, builds the prompt per mode, calls Sonnet.
- `prompts/<mode>__<decl>.txt` — exact prompt sent (for audit / human eval).
- `outputs/slogans_<mode>.jsonl` — one record per decl.

## Run

```bash
pip3 install anthropic
export ANTHROPIC_API_KEY=sk-ant-...

# Control arm first — slogan_context depends on its outputs.
python3 pilot.py isolated
python3 pilot.py slogan_context
python3 pilot.py code_context
```

Add `--dry-run` to skip API calls (resolution + prompt build only).

## Known caveats

- 8 of 37 names are `unresolved` (upstream drift to Mathlib that the local
  apap tree doesn't ship). Harness still emits a prompt with `signature: (decl
  not resolved in DB)`; the slogan will likely be `low` confidence. Surface
  these for human review rather than dropping.
- `code_context` uses dependency **signatures only**, not proof bodies (DB
  doesn't store bodies). This is a known limitation of the v1 pilot.
- `MAX_DEPS = 6` cap on dependency context per decl — adjust in `pilot.py` if
  you want a wider arm.
