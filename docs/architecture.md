# Architecture

`hydropulse.domain` owns immutable scientific contracts and has no infrastructure dependencies. `forecasting` and `events` implement deterministic policy. `adapters` translate external products without discarding provenance. `db` owns revision persistence and canonical reads. `api` exposes the `/api/v1` boundary. The React application consumes only that boundary.

The default database URL is SQLite so unit tests and native development require no service. Compose selects PostgreSQL. An observation revision is unique by source, series, event time, and content hash; canonical reads choose the latest ingested revision without erasing corrections.

## Deliberately gated workflows

AORC, MRMS, and HRRR adapters implement a common return contract but stop with actionable errors until basin masks, object checksums, era coverage, and the seven-day transfer benchmark are frozen. This prevents an accidental multi-hundred-gigabyte backfill. XGBoost, GRU, MLflow, Airflow scheduling, historical RFC/NWM extraction, and promotion consume the same frozen manifests and are not allowed to manufacture evidence when event gates fail.

The baseline is intentionally transparent: it persists the latest stage with a damped six-hour trend and widening uncertainty. Its risk number is explicitly an experimental stage-maximum proxy. It establishes the real source-to-chart path without making a skill claim.

## Adding a model

Produce the `Forecast` contract, keep stage and discharge versions independent, attach an immutable snapshot, and expose a horizon-to-model mapping. Model selection must use validation MAE at 1/6/24 hours, while 48/72-hour results remain visible. Training scalers, percentile thresholds, topology choices, and lag selection must be fit on training folds only.

