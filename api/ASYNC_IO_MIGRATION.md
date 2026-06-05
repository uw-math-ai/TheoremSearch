# Proposal: native async I/O for `/search` and `/mcp`

**Status:** Proposal — *not implemented*. This is the longer-term alternative
to the **threadpool fix** delivered by the companion PR `fix/unblock-event-loop`.
This doc assumes that PR has landed; the "Today" baseline below is the system
*after* it merges.

## Background

`/search` and the `/mcp` tool handler did blocking I/O (psycopg2 + the
synchronous OpenAI client) inside `async def` handlers, which serialized every
request on the event loop and produced the App Runner 502/503/504/429 pattern
(see the App Runner runbook `api/DEPLOYMENT.md`, added by the companion PR
`docs/apprunner-scaling-runbook`).

The companion threadpool fix (`fix/unblock-event-loop`) makes `search` a sync
`def` so FastAPI runs it in its worker **threadpool**, where blocking calls no
longer touch the event loop and requests run in parallel. That is the right fix
for now: ~5 lines, low risk, and it removes the serialization.

## Why consider going further

The threadpool approach has two ceilings:

1. **Concurrency cap.** FastAPI's threadpool defaults to ~40 workers, so one
   instance handles ~40 concurrent `/search` requests before new ones queue.
2. **A thread is parked per in-flight request.** Each `/search` spends most of
   its wall-clock *waiting* on I/O — a ~1s Nebius embedding call plus DB
   round-trips. Under the threadpool model a whole OS thread sits idle for
   that second. Native async would let one instance hold thousands of
   in-flight requests that are merely waiting on I/O, at a fraction of the
   memory/scheduling cost.

For the "thousands of calls per proof" agent workload, native async could cut
the instance count (and thus the Aurora connection footprint) substantially.

## Proposed change

Re-make the search path `async def`, but back it with **non-blocking** clients:

| Today — after the threadpool fix | Proposed (native async) |
|---|---|
| `psycopg2` + `ThreadedConnectionPool` | `asyncpg` pool (or `psycopg` 3 async) |
| `openai.OpenAI` (sync) | `openai.AsyncOpenAI` |
| `def search(...)` (threadpool) | `async def search(...)` awaiting async DB + async embed |
| `routes.mcp` uses `run_in_threadpool(search, ...)` | `routes.mcp` `await search(...)` directly |

Response models, SQL semantics, and the two-stage ANN + rerank logic stay the
same.

## Risks / cost (why it's not a quick swap)

- **Param style & API differ.** `asyncpg` uses positional `$1` placeholders and
  its own execution API — every query in `search.py` / `pagerank.py` and the
  `rds_conn` context manager would be rewritten. (`psycopg` 3 async keeps
  `%(name)s` and is a smaller diff — worth evaluating first.)
- **pgvector over asyncpg** needs explicit type registration
  (`pgvector.asyncpg.register_vector`); the `vector(4096)` / `bit(4096)` casts
  and `SET LOCAL hnsw.*` GUCs must be reproduced on the async connection.
- **Transaction handling** (`SET LOCAL`, commit/rollback in `rds_conn`) must be
  re-expressed against the async pool.
- **Mixed model.** The sync `/graph/*` routes and the in-memory PageRank can
  stay threadpool; only the hot embedding-search path needs porting. Running
  both models in one app is fine but widens the testing surface.
- **Connection accounting changes** — an async pool's sizing math differs from
  the current per-thread model; revisit the budget in the App Runner runbook
  (`api/DEPLOYMENT.md`).

## Suggested plan (incremental)

1. Stand up an async pool (prefer `psycopg` 3 async to minimize SQL churn)
   alongside the existing sync pool — don't rip the old one out.
2. Port `embed_query` to `AsyncOpenAI`.
3. Port `/search` only; keep `/graph/*` and PageRank on the threadpool.
4. Load-test `/search` (the contrast probe in `experiments/`) at high
   concurrency; compare instance count, p50/p99, and Aurora connections vs the
   threadpool baseline.
5. Decide whether the gain justifies porting the remaining DB paths.

## When to do this

Only if a single instance needs to serve **well beyond ~40 concurrent**
embedding-search requests, or if thread/memory overhead from the threadpool
becomes the bottleneck. Until then the shipped threadpool fix is sufficient and
much cheaper to maintain.
