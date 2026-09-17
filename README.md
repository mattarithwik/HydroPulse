# HydroPulse

HydroPulse is a localhost-only river-height forecasting platform for Cedar Rapids, Cartersville, and Goldsboro. It keeps gauge height as the primary target, trains discharge separately, and preserves source revisions. Numerical flood-chance products are disabled.

The repository currently provides the runnable vertical slice and the contracts on which data qualification, weather extraction, neural training, and historical benchmarking build. Expensive backfills are deliberately not run during bootstrap: the implementation plan requires a measured seven-day transfer benchmark and a frozen audit manifest first.

## Quick start

Prerequisites are Docker Desktop and Python 3.12 or newer. This host is approved to use Python 3.14. Docker should have no more than 12 GB allocated.

On macOS systems where Documents is synchronized with iCloud Drive, bulk acquisition data is kept in `data.nosync/`. A local `data` symlink preserves application paths while the `.nosync` suffix prevents iCloud Drive from uploading the dataset.

```bash
cp .env.example .env
make bootstrap
make start
```

Open [http://localhost:8080](http://localhost:8080). API documentation is at [http://localhost:8000/api/docs](http://localhost:8000/api/docs).
If port 8080 is already occupied, start with `HYDROPULSE_UI_PORT=8081 make start` and open
`http://localhost:8081` instead.

For a local UI smoke test without external data, install the Python project, seed clearly marked synthetic observations, and issue a forecast. Synthetic rows are rejected from scientific reporting by their source and qualifier.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
python -m hydropulse.cli seed-demo
uvicorn hydropulse.api:app --reload
curl -X POST -H 'Authorization: Bearer local-development-token' \
  http://localhost:8000/api/v1/operator/forecast/cedar-ia
```

Run the dashboard separately with `cd frontend && npm install && npm run dev`.

## Operating modes

- `make start` uses the direct PostgreSQL path.
- `make start PROFILE=streaming` runs a single-node Kafka/Spark path: the collector publishes
  immutable observation-revision events to Kafka and Spark Structured Streaming writes them through
  the same idempotent PostgreSQL ingestion transaction. Run `make streaming-demo` to exercise it;
  Spark uses five-minute micro-batches and checkpoints offsets under `data/spark-checkpoints/`.
- `make status`, `make stop`, `make backup`, and `make restore DUMP=...` expose the lifecycle.
- `make test` verifies scientific invariants and builds the TypeScript application.
- `make stage1-live` archives current USGS/NWPS payloads; `make stage1-backfill` resumes
  the bounded historical acquisition and `make stage1-audit` reports its completeness.
- `make backup` writes a PostgreSQL backup under the iCloud-excluded `data/backups` directory;
  verify one safely with `make restore-test DUMP=data/backups/<file>.dump`.

Only localhost ports are published. There is no account system and no Redis or object-store emulator.

## Scientific guardrails

- Forecast horizons are relative to issuance, never the newest sample.
- At 91–120 minutes of observation age forecasts are degraded; beyond 120 minutes a new forecast is suppressed.
- Window-maximum event labels use native observations. A crossing proves a positive label; missing coverage cannot prove a negative label.
- 48/72-hour contracts identify the no-future-NWP model explicitly.
- Official thresholds are displayed as height references. HydroPulse does not serve flood probabilities or issue flood warnings.
- NWM comparisons are discharge-only MAE, RMSE, and signed bias; RFC comparison protocols remain distinct.

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the complete qualification and acceptance protocol and [docs/architecture.md](docs/architecture.md) for code boundaries.
Current completion gates and blockers are tracked in
[docs/completion-status.md](docs/completion-status.md).
