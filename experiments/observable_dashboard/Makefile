# One-command loop for the Mathlib-network dashboard.
#
#   make data       regenerate CSV/JSON from the corpus DB
#   make site       build the static site into ./dist
#   make preview    serve the site locally on :4321
#   make deploy     ship ./dist to Cloudflare Pages (requires `wrangler login`)
#   make clean      drop generated artefacts
#
# Override the DB path on the command line:
#   make data DB=/path/to/other_corpus.db TAG=v4.28-2026-06-01

PY      ?= python3
NPX     ?= npx --offline
WRANGLER ?= npx wrangler
DB      ?= $(abspath ../../formalized_graph_v2/data/generated/corpus_v2_mathlib_plus_v4.29.db)
OUT     ?= src/data
TAG     ?= $(shell date -u +%Y-%m-%dT%H-%MZ)
PROJECT ?= mathlib-network

.PHONY: data cycle-data site preview deploy clean install

install:
	$(PY) -m pip install -r requirements.txt
	npm install

data:
	$(PY) build_data.py --db "$(DB)" --out "$(OUT)" --tag "$(TAG)"

cycle-data:
	$(PY) build_cycle_data.py --out "$(OUT)"

site: data cycle-data
	$(NPX) observable build

preview:
	$(NPX) observable preview

deploy: site
	$(WRANGLER) pages deploy dist --project-name=$(PROJECT) --commit-dirty=true

clean:
	rm -rf dist
	rm -f $(OUT)/manifest.json $(OUT)/cycle_consistency.json
