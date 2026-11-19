# Adaptive Global Sales Data Warehouse

A PostgreSQL data warehouse that studies whether **workload-aware adaptive
optimization** (runtime index creation + partition strategy) beats a **static**
physical design when OLAP query patterns shift and ETL keeps writing rows
concurrently.


## The core experiment

Build two systems on the same star schema:

1. **Static** — indexes set once, never changed (the control group).
2. **Adaptive** — a closed loop watches `pg_stat_statements`, detects hot access
   paths, and creates/drops indexes at runtime with safety guards.

Then run **12 configurations** (3 workload types × 4 ETL ingestion rates) against
both and compare latency, index usage, and plan-regression counts.

| | Product-centric | Customer-centric | Temporal-centric |
|---|---|---|---|
| **Zero ETL**   | C1 | C5 | C9 |
| **Low ETL**    | C2 | C6 | C10 |
| **Medium ETL** | C3 | C7 | C11 |
| **High ETL**   | C4 | C8 | C12 |

## Architecture

```
Workload Generator ─┐
                    ├─► PostgreSQL 16 (star schema) ─► pg_stat_statements
ETL Injector ───────┘             ▲                          │
                                  │                          ▼
                          CREATE/DROP INDEX ◄──── Adaptive Engine
                          (guarded DDL)          (monitor→decide→execute)
                                                          │
                                                          ▼
                                                  experiment_log tables
                                                          │
                                                          ▼
                                                   Matplotlib charts
```

### Star schema

- `fact_sales` — central fact, **range-partitioned by year** on `date_key`.
- `dim_item` — drives the *product-centric* query phase.
- `dim_customer` — drives the *customer-centric* query phase.
- `dim_store` — regional dimension.
- `dim_date` — drives the *temporal-centric* query phase.

Synthetic data is **skewed on purpose**: sales concentrate on a few hot items
and customers (Zipf) and on recent dates (recency). That skew is exactly what
makes adaptive indexing worth studying.

## Quick start

### Option A — Docker (recommended for the team)

```bash
cp .env.example .env
pip install -r requirements.txt
make db-up      # start Postgres 16 with pg_stat_statements preloaded
make setup      # schema + baseline indexes + log tables + data load
make psql       # poke around
```

### Option B — existing local Postgres 16

```bash
pip install -r requirements.txt
# ensure pg_stat_statements is in shared_preload_libraries and DB restarted
createdb salesdw   # (and a 'wh' role, or edit .env)
make setup
```

## Running experiments (Phase 2)

Once setup is done, you can run the experiment matrix.

```bash
# One configuration, 30 seconds
python -m src.harness.run_experiment --config C3 --mode static --seconds 30

# The whole 12-config matrix
python -m src.harness.run_experiment --all --mode static --seconds 30

# Repeat 3x for confidence intervals (recommended for the final report)
python -m src.harness.run_experiment --all --mode static --seconds 30 --repeat 3

# See the results
python -m src.harness.report
python -m src.harness.report --csv results.csv

# Clear results between trial runs (warehouse data is untouched)
python -m src.harness.reset_results
```

Individual components can also be run standalone for debugging:

```bash
python -m src.workload.generator --workload product --seconds 20
python -m src.etl.injector --rate medium --seconds 15
```

### Verified baseline behaviour

Measured on 500K rows, static indexes, product workload:

| ETL rate | Median latency | Queries completed |
|---|---|---|
| zero   | 160 ms | 72 |
| low    | 165 ms | 70 |
| medium | 172 ms | 66 |
| high   | 258 ms | 42 |

Latency rises monotonically with ingestion pressure (+61% at high ETL) while
throughput falls — the exact degradation the adaptive engine must counteract.
At baseline **100% of queries use sequential scans**, because the query pools
filter on deliberately unindexed dimension columns (`brand`, `country`,
`quarter`). That is the headroom Phase 3 exploits.

## Running adaptive experiments (Phase 3)

```bash
# Static baseline (control group)
python -m src.harness.run_experiment --config C5 --mode static --seconds 40

# IMPORTANT: reset ETL-injected rows and adaptive indexes between runs so
# static and adaptive start from the identical physical design and table size
python -m src.harness.reset_data --yes

# Adaptive run of the SAME config
python -m src.harness.run_experiment --config C5 --mode adaptive --seconds 40

# Compare
python -m src.harness.report
```

`report.py` now includes a **per-query** breakdown, which is the most
informative view of the results (see below for why).

### How the adaptive engine works

1. **Monitor** (`src/adaptive/monitor.py`) reads `pg_stat_statements`,
   extracts `(table, column)` pairs from query WHERE clauses via SQL parsing,
   and weights each pair by the total execution time of the queries that use
   it. It also reads `pg_stat_user_tables` for sequential-vs-index-scan
   ratios, and `pg_stats` for column selectivity.
2. **Policy** (`src/adaptive/engine.py::_choose`) picks the single best
   candidate that clears three thresholds: enough calls to be a real pattern
   (not noise), a high sequential-scan ratio (the table is actually being
   scanned, not already served by an index), and **low selectivity** — the
   filter must match a small fraction of rows, or an index cannot beat a
   sequential scan no matter how "hot" the column looks.
3. **Executor** (`src/adaptive/executor.py`) builds the index with
   `CREATE INDEX CONCURRENTLY`, bounded by a `lock_timeout` so a busy table
   aborts the adaptation instead of hanging. **Partitioned tables need a
   3-step workaround** since Postgres refuses `CONCURRENTLY` on a partitioned
   parent directly: build concurrently on every leaf partition, create an
   `ONLY` index on the parent, then `ATTACH` each leaf — the parent becomes
   valid once every leaf is attached, with no blocking lock held throughout.
4. **Eviction**: once the engine hits `ADAPTIVE["max_indexes"]`, it drops its
   own least-used index to make room for a better one — this is what makes it
   genuinely *adaptive* to a shifting workload rather than merely additive.

### Design decisions worth knowing about

- **Broad rollups vs selective drill-downs.** Each query pool mixes queries
  that aggregate across a large slice of the warehouse (a sequential scan is
  genuinely optimal for these) with selective drill-downs matching ~3-5% of
  rows (where an index changes the plan entirely). The **per-query** report
  is what reveals this — an aggregate median hides it completely, since
  broad queries dominate the average and stay flat either way.
- **Delta-based scan ratios.** `pg_stat_user_tables` counters are cumulative
  since the database started, not since the current run. The monitor
  snapshots them at the start of every run and measures the delta, so
  decisions reflect the current workload, not leftover history from earlier
  experiments.
- **Partition rollup for scan stats.** Postgres records scan activity against
  leaf partitions, never the parent — a partitioned `fact_sales` always shows
  `seq_scan = 0` on its own. The monitor aggregates child-partition activity
  up to the parent, since that's the level queries are written against and
  indexes are created on.
- **Selectivity gate.** A raw seq-scan ratio isn't enough: a low-cardinality
  column (4-value `season`, 8-value `brand`) can be heavily sequentially
  scanned yet still be a bad index candidate, because the planner will
  correctly choose a full scan over the index anyway. The engine estimates
  selectivity from `pg_stats.n_distinct` and skips any candidate whose filter
  would match more than `ADAPTIVE["max_selectivity"]` (default 5%) of rows.
- **ETL keeps the table growing.** The injector permanently adds rows every
  run — that's realistic ingestion, not a bug — but it means repeated runs
  across a session inflate `fact_sales` well past its original size, and
  "high ETL" quietly becomes a shrinking fraction of an ever-larger table.
  Run `python -m src.harness.reset_data` before a batch of runs you intend to
  compare, so every run starts from the same table size.
  The trim identifies original rows by their `created_at`: the generator
  loads everything in one transaction so all 500K share a single timestamp,
  while each ETL batch commits separately and gets its own. Deleting
  everything except that modal timestamp is exact and stays exact no matter
  how many times it runs.

### Verified results (500K rows, single 40s runs)

Per-query latency, static vs adaptive, aggregated across product/customer/
temporal workloads:

| Query type | Example | Improvement |
|---|---|---|
| Selective drill-down | `c7_whale_customers` (net_amount > threshold) | **38–58%** faster |
| Selective drill-down | `t7_promo_seasonality` (discount > threshold) | **48–58%** faster |
| Broad rollup | `p1_revenue_by_category` | ~0%, occasionally slightly slower |

The pattern holds even under **high concurrent ETL** (customer workload,
~350K rows injected during a 40s run): selective queries still improved
32–38% while broad queries stayed flat. This is the core proposal claim
made measurable — adaptive indexing helps exactly where a sequential scan
stops being optimal, and does not help (and should not be expected to help)
where a sequential scan already is optimal.

A guarded-DDL test confirmed the safety design: holding an exclusive lock on
a partition and attempting a concurrent index build on it aborts cleanly
after `ddl_timeout_ms` (default 5s) rather than blocking, exactly as the
proposal's Risks section specifies.

## Adaptive partition optimization

The second optimization axis from the proposal: adapting the *partition
layout*, not just the indexes.

### The problem

A range-partitioned fact table is defined over fixed boundaries. A
continuously-ingesting ETL pipeline eventually writes past the newest
boundary, and those rows fall into the DEFAULT catch-all partition. The third
consequence is the one that actually hurts:

1. DEFAULT grows without bound and loses the benefits of partitioning.
2. Its statistics degrade as it becomes a mixed bag of date ranges.
3. **It blocks its own fix.** Once DEFAULT holds rows for a range, Postgres
   refuses to attach a proper partition covering that range:

   ```
   ERROR: updated partition constraint for default partition
          "fact_sales_default" would be violated by some row
   ```

   The warehouse gets stuck, and the longer it runs the more data must be
   migrated to recover.

### The two mechanisms

| Mechanism | When | Cost (measured) |
|---|---|---|
| **Proactive provisioning** | Ingestion frontier comes within `partition_lead_days` of the range end | **~70 ms** — empty partition, no data movement |
| **Reactive drain** | Rows are already stranded in DEFAULT | **~1,700 ms** for 40–60K rows, and grows with accumulation |

That ~24× asymmetry is itself a reportable finding: adaptation that
anticipates the workload is nearly free, while adaptation that reacts to a
problem already underway is expensive *and* contends with the ETL stream that
caused it.

### Verified behaviour

Identical config (C11: temporal workload, medium ETL, 45s), ETL advancing the
ingestion frontier past the 2025 boundary:

| Mode | Rows stranded in DEFAULT | Queries completed |
|---|---|---|
| static | **25,000** | 269 |
| adaptive | **0** (provisioned `fact_sales_2026` in 70 ms) | 314 |

The engine runs partition adaptation *before* index adaptation each cycle,
because an unprovisioned frontier silently corrupts the physical design,
whereas a missing index merely costs latency.

### Controlling it

```python
# src/config.py -> ADAPTIVE
"adapt_partitions":    True,   # master switch (False = indexing only)
"partition_lead_days": 45,     # how far ahead to provision
"hot_partition_share": 0.05,   # min scan share for a partition to count as hot
```

```python
# src/config.py
ETL_ADVANCE_DAYS_PER_BATCH = 1.5   # 0 = ingestion stays inside existing
                                   # partitions (control condition)
```

Setting `adapt_partitions: False` gives you an indexing-only arm, so the two
optimization axes can be evaluated in isolation — useful for the report's
ablation discussion.

## Live dashboard (for the demo)

A small Flask app that makes the system visible while it runs — useful for
the project demo and presentation, where watching the engine build an index
in real time lands better than reading terminal output afterwards.

```bash
pip install -r requirements.txt     # adds flask
python -m ui.app
# open http://localhost:5000
```

What it shows:

- **Partition layout**, with rows stranded in DEFAULT highlighted in red and
  an explanation of why that state is a problem (it blocks creating the
  partitions those rows belong in).
- **Adaptive indexes** currently in place, with their scan counts and size —
  empty means the physical design is at its static baseline.
- **Run controls**: pick any config C1–C12, choose static or adaptive, set a
  duration, and launch. The engine's output streams into the page live, with
  index builds, partition provisioning, and aborts colour-coded.
- **Per-query static vs adaptive** comparison with improvement bars.
- **Adaptation log**: every decision the engine made and what it cost.
- **Reset to clean frontier** (green button) — the one that matters for
  demos. Drops adaptive indexes, removes post-baseline rows, drops any
  partition the engine provisioned or drained into, and trims ETL rows, all
  in one click. Without this the demo silently stops working: once a
  partition beyond the baseline exists, ETL has somewhere valid to write, so
  nothing strands and the engine has no partition work left to show.
- Finer-grained resets for clearing results, dropping adaptive indexes, and
  trimming ETL rows individually.

The UI drives the same `run_config()` the CLI does and reads the same log
tables — it is a window onto the system, not a second implementation.

### Suggested demo sequence

Click **⟲ Reset to clean frontier** before each run below — the three
partition scenarios are only distinguishable from a clean starting state.

1. **Proactive path.** Reset, then run **C11 / adaptive / 45s**. The engine
   provisions `fact_sales_2026` in well under a second, *before* any row
   needs it. DEFAULT stays empty. (~60–110 ms, no data movement.)
2. **The failure it prevents.** Reset, then run **C11 / static / 45s**. ETL
   crosses the 2025 boundary with no partition ready and ~20K rows strand in
   DEFAULT — the partition panel turns red and warns that these rows now
   block creating the partition they belong in.
3. **Reactive recovery.** Without resetting, run **C11 / adaptive / 45s**.
   The engine drains the stranded rows into a proper partition. Note the
   cost against step 1: roughly 400 ms for 24K rows versus 60 ms to have
   provisioned ahead — and recovery cost grows with how long the problem
   went unnoticed.
4. **Query improvement.** Reset, run **C5 / static / 45s**, reset again, then
   **C5 / adaptive / 45s** to populate the per-query table and show the
   selective-vs-broad split.

Steps 1–3 are the strongest four minutes of the demo: adaptation prevents the
problem cheaply, static hits it, and adaptation can still recover — but at
several times the cost.

## Validating the whole system

One command exercises every claim the project makes and reports pass/fail per
component, so a failure points at the specific part rather than "something is
wrong".

```bash
python -m src.harness.acceptance            # full suite, ~7 min
python -m src.harness.acceptance --quick    # skips partition + safety, ~3 min
```

It checks, in order: environment and extensions; schema, partitioning,
pruning and data skew; that the static control group builds no indexes; that
each workload causes a *different* selective column to be indexed; that
selective queries improve while broad rollups do not; that partitions are
provisioned ahead of the ingestion frontier and stranded rows are drained;
that index DDL aborts under lock contention instead of blocking; and that the
figures and CSVs generate.

Every check resets the physical design and table size first — a test that
only passes from a lucky starting state is not a test.

## Producing report results (Phase 4)

### Run the full matrix

```bash
# Recommended for the report: all 12 configs, both modes, 3 repetitions
python -m src.harness.run_matrix --seconds 40 --repeat 3

# Faster sanity check of the whole matrix
python -m src.harness.run_matrix --seconds 40 --repeat 1

# One workload at a time (useful if you want to spread it over sessions)
python -m src.harness.run_matrix --workload customer --seconds 40 --repeat 3
```

`run_matrix` resets adaptive indexes **and** trims/VACUUMs ETL-injected rows
before every single run, so each run starts from an identical physical design
and table size. Doing this by hand across 72 runs is where mistakes happen;
this is why the script exists.

### Generate figures and tables

```bash
python -m analysis.plots        # -> analysis/figures/*.png
python -m analysis.export_csv   # -> analysis/exports/*.csv
python -m src.harness.report    # console summary
```

Figures produced:

| File | Answers |
|---|---|
| `fig1_latency_by_etl.png` | Does latency degrade as ETL rises, and does adaptation hold it back? |
| `fig2_per_query_improvement.png` | **The headline result** — where adaptation helps and where it doesn't |
| `fig3_seqscan_and_plans.png` | Did the physical design actually change? |
| `fig4_adaptation_overhead.png` | What did the optimization cost? |
| `fig5_partition_adaptation.png` | Proactive provisioning vs reactive draining |

CSVs land in `analysis/exports/` and open directly in Excel for report tables.

### Run duration matters more than you'd expect

The engine waits one poll interval (default 10s) before its first decision,
then the new index needs time to actually serve queries. **A 10-second run
measures adaptive mode almost entirely in its pre-adaptation state.** In
testing, 8-second runs showed ~5% improvement on selective queries while
40-second runs of the same configs showed 30-60%. `run_matrix` warns if you
pass a duration under 3x the poll interval; use **40 seconds or more** for
anything you intend to report.

### Reading the figures honestly

- **`fig2` is the figure that matters.** Adaptive indexing helps selective
  drill-down queries a great deal and broad aggregate scans not at all, and
  an aggregate median averages those two effects into something misleadingly
  small. Report the per-query breakdown, not just the headline number.
- **A ~0% result on broad rollups is a correct result, not a failure.** A
  full table scan is genuinely the optimal plan for those queries; an
  optimizer that "improved" them would be doing something wrong.
- **`fig3`'s seq-scan panel sits near 100% for both modes.** The metric flags
  a plan if *any* node is a sequential scan, and the small dimension tables
  are always scanned sequentially even when the fact table has switched to a
  bitmap index scan. Use the plan-diversity panel as the real signal that
  plans changed.
- **Measurement noise is real.** Run the matrix when the machine is otherwise
  idle, keep the project **outside cloud-synced folders** (OneDrive/Dropbox
  syncing mid-run competes for disk I/O and skews individual runs), and use
  `--repeat 3` so single-run outliers average out.

## Project layout

```
adaptive-warehouse/
├── docker-compose.yml         # Postgres 16 + pg_stat_statements
├── Makefile                   # make db-up / setup / load / psql ...
├── requirements.txt
├── .env.example
├── sql/
│   ├── 01_schema.sql          # star schema (partitioned fact table)
│   ├── 02_baseline_indexes.sql# STATIC control-group indexes
│   └── 03_experiment_log.sql  # run / query_sample / adaptive_action tables
├── src/
│   ├── config.py              # connection + scale + experiment matrix + tuning
│   ├── db.py                  # psycopg2 helpers
│   ├── data_gen/generate.py   # ✅ synthetic TPC-DS-shaped data loader
│   ├── workload/
│   │   ├── queries.py         # ✅ 3 query pools (product/customer/temporal)
│   │   └── generator.py       # ✅ runs queries, measures via EXPLAIN ANALYZE
│   ├── etl/injector.py        # ✅ concurrent ETL at 4 configurable rates
│   ├── adaptive/
│   │   ├── monitor.py          # ✅ reads pg_stat_statements, ranks candidates
│   │   ├── executor.py         # ✅ guarded, partition-aware concurrent DDL
│   │   ├── partitions.py       # ✅ adaptive partition provisioning + drain
│   │   └── engine.py           # ✅ closed monitor→decide→act loop (thread)
│   └── harness/
│       ├── run_experiment.py  # ✅ orchestrates the 12-config matrix
│       ├── report.py          # ✅ summary + static-vs-adaptive + per-query
│       ├── reset_results.py   # ✅ clear results between trial runs
│       ├── reset_data.py      # ✅ trim ETL-injected rows + VACUUM
│       ├── run_matrix.py      # ✅ full 12x2 matrix with reset discipline
│       └── acceptance.py      # ✅ end-to-end pass/fail validation suite
├── analysis/
│   ├── plots.py               # ✅ report figures (Matplotlib)
│   └── export_csv.py          # ✅ CSV exports for report tables
└── ui/
    ├── app.py                 # ✅ Flask dashboard backend
    └── templates/index.html   # ✅ live dashboard page
```

## Roadmap

- [x] **Phase 1** — Environment, star schema, baseline indexes, log tables, data loader.
- [x] **Phase 2** — Workload generator (3 query pools) + concurrent ETL injector + experiment harness + reporting.
- [x] **Phase 3** — Adaptive engine: monitor `pg_stat_statements`, decide, execute guarded DDL.
- [x] **Phase 4** — Run the 12×2 matrix, collect logs, plot static vs adaptive.
