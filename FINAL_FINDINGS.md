# HydroPulse final findings

Project status: **implementation and research summary complete**

Evidence frozen: **2026-09-21**

Historical archive cutoff: **2026-09-13**

## Executive conclusion

HydroPulse successfully demonstrates a reproducible, localhost-only river-stage forecasting
platform for Cedar Rapids, Cartersville, and Goldsboro. It acquires and revisions observations,
builds leakage-resistant chronological datasets, trains ridge, XGBoost, and GRU models, serves
live stage forecasts, records shadow predictions, and supports both direct PostgreSQL and
Kafka/Spark ingestion paths.

The defensible final product is **continuous gauge-height forecasting with uncertainty and
official thresholds shown only as reference lines**. The data audit found too few independent
calibration-period flood episodes to support numerical flood-probability claims. The transparent
target-only ridge model therefore remains the public candidate. No XGBoost or GRU challenger met
the complete promotion policy, and the untouched 2024-01-01 through 2026-09-13 final test was not
opened.

## Evidence produced

- 1,962,321 valid target-stage samples were audited across the three basins.
- The data split and upstream lag choices were frozen before model comparison.
- Ridge, XGBoost, and three-seed GRU stage models were trained for all targets without using final
  test examples.
- Live ridge forecasts and six challenger forecasts were recorded successfully on four calendar
  days. September 20 was missed while Docker was offline, so this is not a completed seven-day
  continuity trial.
- Kafka/Spark ingestion, checkpoint restart recovery, PostgreSQL persistence, the FastAPI service,
  React dashboard, Prometheus monitoring, backup, and isolated restore were implemented and
  exercised.
- The final verification run passed 36 backend tests, the production frontend build, and Ruff.

## Development-set model results

Values below are stage MAE in feet on the frozen 2018-2020 development validation period. They
are model-selection evidence, not final-test estimates.

| Target | Model | 1 h | 6 h | 24 h | High-stage MAE | Promotion result |
|---|---|---:|---:|---:|---:|---|
| Cedar Rapids | Ridge | 0.021 | 0.098 | 0.299 | 1.126 | Retained champion |
| Cedar Rapids | XGBoost | 0.040 | 0.095 | 0.283 | 1.087 | Not promoted |
| Cedar Rapids | GRU | 0.036 | 0.076 | 0.208 | 0.939 | Not promoted |
| Cartersville | Ridge | 0.011 | 0.135 | 0.734 | 2.930 | Retained champion |
| Cartersville | XGBoost | 0.057 | 0.245 | 0.849 | 2.810 | Not promoted |
| Cartersville | GRU | 0.028 | 0.158 | 0.713 | 2.847 | Not promoted |
| Goldsboro | Ridge | 0.005 | 0.060 | 0.461 | 0.920 | Retained champion |
| Goldsboro | XGBoost | 0.031 | 0.135 | 0.581 | 0.904 | Not promoted |
| Goldsboro | GRU | 0.013 | 0.067 | 0.411 | 0.681 | Not promoted |

The GRU often improved longer-horizon and high-stage error, but it regressed at the critical
one-hour horizon. The policy intentionally prevents a longer-horizon gain from hiding a
headline-horizon regression.

## Scientific findings

1. **Stage prediction is supportable; official flood probability is not.** Even the action-stage
   calibration block contained only six pooled storm clusters. Minor, moderate, and major stages
   contained one, two, and zero respectively, so every official-threshold probability gate failed.
2. **Simple models are hard to beat at short horizons.** River stage is strongly persistent. The
   target-only ridge model produced the best one-hour validation MAE for every target.
3. **Neural models show conditional promise.** The GRU improved many 24-72 hour and high-stage
   metrics, most clearly at Cedar Rapids and Goldsboro, but did not pass the all-horizon promotion
   rule.
4. **Upstream information was not a universal win.** Qualified upstream signals were retained for
   research, but the target-only ridge variant was selected for all three public candidates.
5. **Operational reliability matters as much as model accuracy.** The streaming path recovered
   from checkpoints and avoided duplicate durable writes, while the shadow trial also exposed the
   practical dependency on Docker availability.

## Claim boundary

This project demonstrates a working local forecasting system and reports frozen development
results. It does **not** claim production readiness, calibrated flood probabilities, superiority
to official RFC/NWM forecasts, weather-enhanced skill, a completed seven-day soak, or independent
final-test performance. Those claims require new, explicitly scoped work; they are not hidden
requirements for the current project scope.

## Reproduction

```bash
make test
make lint
make start
```

Detailed provenance remains in `data/reports/`, `data/manifests/`, and the model artifacts under
`data/models/`. These local evidence files are intentionally excluded from Git because of their
size and machine-specific paths.
