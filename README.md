# conflict-exo-pg

Aurora PostgreSQL Serverless v2 with **minimum capacity 0 ACU and auto-pause** — a database that costs
nothing while nobody is looking at it.

The dataset is beside the point. The point is the managed service:

```toml
[[managed_services]]
kind = "postgres"
variant = "aurora_postgres_serverless_v2"
size = "small"

  [managed_services.extensions]
  min_acu = 0
  max_acu = 2
  seconds_until_auto_pause = 300
  engine_version = "16.6"
```

After five idle minutes Aurora scales its compute to zero and stops billing for
it. Storage keeps costing roughly a dime per GB-month; compute costs nothing.

## The cold start is the demo

The first query after a pause pays a resume. This app **measures and shows**
that rather than hiding it behind a connection pool — which is also why there
is no pool. The front page charts recent connection latency with a 2-second
resume threshold marked, and colours any bar past it differently.

A warm connect to a running writer is tens of milliseconds. Seconds means the
cluster was asleep and woke up for you.

## Topology

| | |
|---|---|
| Workloads | `web` (`deployment`, public, 1 replica) |
| Managed services | `postgres` / `aurora_postgres_serverless_v2` |
| Data | the NASA Exoplanet Archive, seeded into the database on first boot |
| Idle cost | one small pod, plus Aurora storage — no compute |

## Two deliberate choices

**Liveness never touches the database.** A paused Aurora would otherwise read
as an unhealthy pod and get restarted mid-resume. `/health` answers from the
process alone.

**Seeding runs off the request path**, so a cold start plus the initial import
cannot hold the readiness probe open. It is idempotent: a restart against a
populated database is a count query, not a re-import.

## Endpoints

| Path | Purpose |
|---|---|
| `/` | The dashboard |
| `/health` | Probe target — deliberately does not query |
| `/debug` | Pod identity, binding presence, seed state, recent connect history |
| `/selftest` | `SELECT 1` plus a row count, reporting whether the latency included a resume |
| `/api/connections` | The full cold-start record |

## Deploying

```sh
astro app register --project-id <demos-project-guid> \
  --source-repo ConflictHQ/conflict-exo-pg \
  --build-mode platform_build
astro app deploy --wait
```

The platform creates the ECR repository, mints the build and runtime roles,
builds in-cluster with Kaniko and rolls out. Nothing is built locally.

## Verified

The manifest above was checked against the real driver, not assumed:
`AuroraDriver._validate_scaling` accepts it, and rejects both
`min_acu = 0.5` with auto-pause ("auto-pause requires min_acu=0") and
`min_acu = 0.3` ("capacities must use 0.5 ACU increments").

Data: [NASA Exoplanet Archive](https://exoplanetarchive.ipac.caltech.edu/), operated by Caltech under contract with NASA.
