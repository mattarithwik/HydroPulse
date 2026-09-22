# HydroPulse

HydroPulse is a local river-stage forecasting platform for three U.S. gauge locations:
Cedar Rapids, Iowa; Cartersville, Virginia; and Goldsboro, North Carolina. It combines historical
and live hydrologic data, leakage-resistant model evaluation, operational forecasting, and an
optional Kafka/Spark ingestion path in one reproducible project.

The application forecasts gauge height rather than issuing flood warnings. Official flood stages
are displayed as reference lines, while numerical flood-probability products remain disabled
because the historical calibration data did not contain enough independent flood events to
support them responsibly.

## Highlights

- Live and historical USGS/NWPS ingestion with immutable source revisions
- Chronological train, validation, calibration, and untouched-test boundaries
- Ridge, XGBoost, and three-seed PyTorch GRU forecasting experiments
- Forecast horizons of 1, 6, 24, 48, and 72 hours
- FastAPI service and React/TypeScript dashboard
- PostgreSQL storage with backup and isolated restore workflows
- Optional Kafka and Spark Structured Streaming ingestion with idempotent persistence
- Prometheus metrics and Grafana dashboards
- 36 backend tests plus frontend production-build verification

## Findings

The target-only ridge model remains the public candidate because it produced the strongest
one-hour validation accuracy for all three locations. GRU challengers improved several longer
horizons and high-stage subsets, but none passed the complete promotion policy. The frozen final
test was intentionally left unopened, so the repository makes no independent test-performance or
production-readiness claim.

Detailed results and limitations are documented in [FINAL_FINDINGS.md](FINAL_FINDINGS.md).

## Architecture

```text
USGS / NWPS
     |
     v
Collectors -----> PostgreSQL <----- Spark <----- Kafka
                       |
             Features and models
                       |
                  FastAPI API
                       |
               React dashboard
```

Direct PostgreSQL ingestion is the default. The streaming profile routes observation events
through Kafka and Spark before writing through the same idempotent database transaction. Both
paths share the feature, model, and serving contracts.

See [docs/architecture.md](docs/architecture.md) for component boundaries and
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full scientific protocol.

## Prerequisites

- Docker Desktop
- Python 3.12 or newer
- Node.js and npm for standalone frontend development
- Up to 12 GB of memory allocated to Docker

The project is designed for local execution. Services bind to localhost, and bulk datasets and
model artifacts are intentionally excluded from Git.

## Quick start

```bash
cp .env.example .env
make bootstrap
make start
```

Then open:

- Dashboard: [http://localhost:8080](http://localhost:8080)
- API documentation: [http://localhost:8000/api/docs](http://localhost:8000/api/docs)

If port 8080 is occupied:

```bash
HYDROPULSE_UI_PORT=8081 make start
```

## Local development

Create the Python environment and install development dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Run the API and frontend independently:

```bash
uvicorn hydropulse.api:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

For a UI smoke test without external data, seed explicitly marked synthetic observations:

```bash
python -m hydropulse.cli seed-demo
```

Synthetic rows are excluded from scientific reporting through their source and qualifier fields.

## Common commands

| Command | Purpose |
|---|---|
| `make start` | Start the direct PostgreSQL application stack |
| `make start PROFILE=streaming` | Start the Kafka/Spark ingestion profile |
| `make status` | Show service and resource status |
| `make stop` | Stop services without deleting durable data |
| `make test` | Run backend tests and build the frontend |
| `make lint` | Run Python lint checks |
| `make stage1-live` | Archive current USGS and NWPS payloads |
| `make stage1-audit` | Generate the current data-quality audit |
| `make streaming-demo` | Exercise Kafka-to-Spark-to-PostgreSQL ingestion |
| `make backup` | Create a PostgreSQL backup |
| `make restore-test DUMP=...` | Verify a backup in an isolated database |

## Scientific safeguards

- Forecast horizons are relative to issuance time, not the newest observation.
- Forecasts are marked degraded when target observations are 91–120 minutes old and suppressed
  beyond 120 minutes.
- Window-maximum labels use native observations so short threshold crossings are not lost.
- Missing coverage cannot prove a negative threshold event.
- Normalization, percentile thresholds, and upstream lag selection use training data only.
- The 2024-01-01 through 2026-09-13 test interval remains untouched.
- Official thresholds are contextual references; HydroPulse does not issue warnings or calibrated
  flood probabilities.

## Data and generated artifacts

Historical data, reports, model artifacts, backups, and runtime checkpoints are stored under the
local `data` path and are excluded from version control. On macOS systems with iCloud-synchronized
Documents, `make bootstrap` uses `data.nosync/` with a `data` symlink to avoid syncing large local
datasets.

Project status and explicit claim boundaries are recorded in
[docs/completion-status.md](docs/completion-status.md).
