# Completion status

Last verified: 2026-09-17.

## Working locally

- Native target-stage history through the frozen 2026-09-13 archive cutoff.
- Qualified connected upstream history and training-only lag analysis.
- Immutable training, validation, calibration, and untouched-test manifest.
- Causal hourly stage datasets for all three targets.
- Persistence, target-only ridge, and upstream ridge development comparisons.
- Calibrated target-only candidate forecasts at 1, 6, 24, 48, and 72 hours.
- Live six-hour USGS reconciliation, outage catch-up, and candidate shadow runs.
- Local API and dashboard, candidate labeling, threshold-height context, and no flood
  probability claims.
- Prometheus collection, bounded Docker resources, PostgreSQL backup, and isolated restore test.

## Gates still open

1. **Seven elapsed shadow days.** The candidate started shadow operation at
   2026-09-17 04:28 UTC. Promotion cannot be assessed before 2026-09-24 04:28 UTC.
2. **Independent final test.** The 2024-01-01 through 2026-09-13 test remains unopened.
   It is opened once, only after the research release and model choice are frozen.
3. **Weather qualification.** AORC/MRMS/HRRR adapters remain deliberately disabled until basin
   masks, object versions, source-era availability, and a bounded transfer benchmark are frozen.
   No weather-enhanced skill claim is currently possible.
4. **Official historical comparisons.** IEM RFC and historical operational NWM extraction and
   availability audits have not been run, so no comparison with official forecasts is claimed.
5. **Advanced challengers.** XGBoost and GRU experiments are shadow-only; the currently runnable
   product uses the transparent ridge candidate.
6. **Streaming soak.** Kafka publishing and Spark Structured Streaming persistence are implemented,
   but the separate seven-day streaming-profile soak and direct/streaming parity report remain open.

Flood-probability modeling is intentionally out of scope. The calibration period contains only
one qualifying flood episode, and the product reports stage height and uncertainty instead.
