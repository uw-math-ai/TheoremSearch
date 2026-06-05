# Deployment & scaling runbook (AWS App Runner)

This service is FastAPI, served on **AWS App Runner** (verify in the console;
the public hostname `api.theoremsearch.com` is a CNAME to
`*.us-west-2.awsapprunner.com`, and responses carry `server: envoy`). App
Runner runs the container behind an **Envoy proxy + an internal load
balancer** on Fargate, talks to an **Aurora PostgreSQL** cluster, and calls
**Nebius Token Factory** for embeddings.

The App Runner autoscaling configuration is **not** stored in this repo — it
lives in the AWS account as an `AutoScalingConfiguration` resource. This file
records the recommended settings and the reasoning, so the infra config has a
reviewed source of truth.

> All numbers here are **defaults / recommendations to verify against the live
> service**, not a claim about the current configuration. Check the console or
> `aws apprunner describe-service` before changing anything.

> **Describes the post-fix system — merge the companion API PRs first (or
> together with this one).** This runbook references behavior that those PRs
> introduce:
> - `fix/unblock-event-loop` — moves `/search` & `/mcp` blocking work into the
>   threadpool (the "fixed" code path below).
> - `chore/configurable-db-pool` — adds the `RDS_POOL_MIN` / `RDS_POOL_MAX` /
>   `RDS_STATEMENT_TIMEOUT_MS` env vars below. Until it lands, those are
>   constants in [`db.py`](db.py) and require a code edit to change.
> - `fix/pagerank-graph-warming` — adds the `PAGERANK_ENABLED` kill-switch below.

---

## Why this matters: where 502 / 503 / 504 / 429 come from

Those status codes are emitted by **App Runner / Envoy**, never by the
application (the app's only failure path returns HTTP 500). They are almost
always a symptom of **one instance being unable to keep up with the
concurrency App Runner routes to it**:

| Code | App Runner meaning |
|------|--------------------|
| 504  | A request exceeded App Runner's request timeout (≈120s). |
| 502  | The instance dropped/closed the connection — health-check failure + recycle, a crash, or an OOM kill. |
| 503  | No healthy instance available (just-recycled, deploying, or starting). |
| 429  | Deliberate load-shedding: an instance's request queue is full and App Runner is still scaling out. |

The historical trigger was a code bug — `/search` and `/mcp` were `async def`
doing blocking I/O, which serialized every request on the event loop, so one
instance effectively handled ~1 request at a time while App Runner pushed up
to `MaxConcurrency` (default **100**) at it. That code path is fixed by the
companion PR `fix/unblock-event-loop` (the handlers run in FastAPI's
threadpool once it lands). The settings below keep the infrastructure side from
re-creating the same symptom.

Throughput note: with the threadpool fix, one instance still handles only as
many concurrent `/search` calls as it has threadpool workers (~40), and each
call holds its worker for the full request — dominated by the ~1s embedding
round-trip. Those ~40 workers are shared across *all* sync routes (`/search`,
`/graph/*`, `/graph/pagerank`), so steady-state per-instance `/search`
throughput is on the order of tens of req/s before requests queue. That's why
the recommended `MaxConcurrency` below is ~40, not higher.

---

## Recommended autoscaling configuration

| Setting | Default | Recommended | Why |
|---|---|---|---|
| **Max concurrency** | 100 | **~40** | The app processes blocking requests in FastAPI's threadpool (default 40 workers) and the DB pool maxes at `RDS_POOL_MAX` (default 40). Past ~40 concurrent, an instance just queues — so App Runner should scale *out* there instead of piling more onto one instance. Max allowed is 200. |
| **Min size** | 1 | **≥2** | App Runner pauses idle instances; the first request after idle pays a cold start (measured ~7s vs ~1s warm). ≥2 warm instances removes most cold-start 504s and adds redundancy during recycles. |
| **Max size** | 25 | **bounded by the DB connection budget** | See below. |

### Bounding Max size by the Aurora connection budget

Each running instance opens up to `RDS_POOL_MAX` connections **per distinct
dbname** it uses (currently `postgres` and `v2`). Worst case:

```
total_connections ≈ MaxSize × RDS_POOL_MAX × (#dbnames)
```

Keep that **under the Aurora cluster's `max_connections`** (Aurora derives it
from the instance class; check `SHOW max_connections;`). Example: with
`RDS_POOL_MAX=40`, 2 dbnames, and a cluster `max_connections` of 1000, a safe
`MaxSize` is ≲ 12. To scale wider, either lower `RDS_POOL_MAX` (see
[`db.py`](db.py)) or front Aurora with **RDS Proxy** and point the service at
the proxy endpoint.

---

## Applying it (AWS CLI)

> Flag names vary slightly by CLI version — confirm with
> `aws apprunner create-auto-scaling-configuration help`.

```bash
# 1. Create a new autoscaling configuration revision.
aws apprunner create-auto-scaling-configuration \
  --auto-scaling-configuration-name theoremsearch-api \
  --max-concurrency 40 \
  --min-size 2 \
  --max-size 12 \
  --region us-west-2

# 2. Associate it with the service (re-deploys the service).
aws apprunner update-service \
  --service-arn <SERVICE_ARN> \
  --auto-scaling-configuration-arn <ASC_ARN_FROM_STEP_1> \
  --region us-west-2
```

### Health check

Point the App Runner health check at the lightweight `GET /ping` (HTTP
protocol, not TCP) so a wedged event loop is actually detected:

```bash
aws apprunner update-service \
  --service-arn <SERVICE_ARN> \
  --health-check-configuration 'Protocol=HTTP,Path=/ping,Interval=10,Timeout=5,HealthyThreshold=1,UnhealthyThreshold=5' \
  --region us-west-2
```

A **TCP** health check can pass against an instance whose HTTP handler is
stuck (the OS still completes the TCP handshake), so App Runner would keep
routing to a dead-for-HTTP instance → 502/504. HTTP `/ping` avoids that.

### Request timeout

App Runner's request timeout is ≈120s by default. Confirm the current value in
the console; requests that legitimately need longer than the timeout will
surface as 504 regardless of app health.

---

## Application env vars that affect scaling

Set these on the App Runner service (runtime environment), not in code:

| Var | Default | Effect |
|---|---|---|
| `RDS_POOL_MAX` | 40 | Max DB connections per instance per dbname. Lower it to raise the safe `MaxSize`. |
| `RDS_POOL_MIN` | 5 | Min pooled connections per instance per dbname. |
| `RDS_STATEMENT_TIMEOUT_MS` | 10000 | Per-statement timeout for request-shaped queries. |
| `PAGERANK_ENABLED` | true | Set `false` to disable `/graph/pagerank` (returns 404) — it holds the full ~12M-node graph in memory and is the most likely OOM source. |

---

## Verifying a change

Re-run the concurrency contrast probe (in `experiments/`): fire N concurrent
requests at `/search` and at `/graph/embedding` and compare wall-clock. After
the threadpool fix both should stay roughly **flat** as concurrency rises;
linear growth on `/search` means a blocking call slipped back onto the event
loop. Watch the App Runner `RequestLatency`, `4xxStatusResponses`, and
`5xxStatusResponses` CloudWatch metrics, and Aurora `DatabaseConnections`,
during a load test.

---

## Note

AWS App Runner is closed to new customers and being wound down. If the service
is replatformed, **ECS/Fargate behind an ALB** gives direct control over the
request timeout, health-check semantics, per-target concurrency, and
connection draining — all of the levers this runbook works around.
