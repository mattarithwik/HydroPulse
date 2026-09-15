# HydroPulse decision log

This file records design history; IMPLEMENTATION_PLAN.md is the current implementation contract. Historical notes below describe earlier review decisions, not additional implementation requirements.

## Initial engineering revisions

### Changes following the engineering review

| Previous decision | Revised decision |
|---|---|
| Recent three-year weather training window | Use the available continuous stage record from 2007 onward and long-history AORC; evaluate live-weather source shift explicitly |
| Fixed six-month probability calibration window | Audit independent flood episodes first; select chronological development splits by a documented gate |
| Thirty-minute target staleness cutoff | Normal/degraded/unavailable states at 90/120 minutes, with latency-aware training |
| Primary autoregressive 96-step model | Direct stage and window-maximum models first; direct hourly GRU is the principal neural model |
| Guaranteed calibrated official flood probabilities | Evidence-gated calibration; experimental estimates are explicitly identified and sparse thresholds do not create probability-triggered alerts |
| Equal-weight joint stage/discharge loss | Independent discharge model, so stage accuracy is not diluted |
| Redis and S3-compatible local storage | PostgreSQL, local Parquet/DuckDB, and MLflow filesystem artifacts |
| Streaming scale implied by small gauge network | Kafka/Spark retained explicitly as portfolio engineering requirements |
| Weekly retraining with unspecified promotion data | Monthly/event-triggered candidates and a separate rolling, prospective promotion window |
| Dashboard near the end | Live forecast and minimal dashboard in the first vertical slice |
| 24-hour soak | Seven-day soak including daily maintenance and one weekly maintenance cycle |

## Evidence and resource qualifications from earlier reviews

The review's exact flood counts and maxima have not been independently reproduced. Treat them as a serious finding requiring the following audit, not as verified counts in the experiment report. Annual peaks can help discover events but cannot establish duration, number of episodes, or all within-window labels. The review's proposed 32 GB minimum is also not a measured requirement: validate the reduced stack on this 24 GB host.

Review disposition: accept event scarcity as an audit blocker for probability claims; accept latency, official baselines, split isolation, source versioning, local storage simplification, and vertical-slice sequencing. Preserve the user's three basins, trained discharge output, and Kafka/Spark portfolio scope. Do not adopt unverified exact event counts, universal 32 GB requirements, unlimited HEFS history, or a timeless stage/discharge rating conversion.

## Historical benchmark correction

The absence of long-term archives in the NWPS API was incorrectly generalized to absence of historical operational forecasts. Verified IEM RVF products provide historical RFC stage forecasts, and Google's public national-water-model bucket provides historical operational NWM discharge output. Both are now frozen-test benchmarks, with explicit archive-availability assumptions and bounded extraction.

The implementation document now states decisions directly. Split freezing occurs at stage 1 exit, direct-mode latency has its own acceptance target, and dashboard views have accurate delivery stages. Scheduling and effort-sizing suggestions were not adopted, following the explicit instruction to ignore scheduling comments. No scope was deferred.

## RFC protocol separation and sampled NWM claim limits

Split RFC evaluation into creation-time-aligned forecasts at SHEF DC/native RFC valid times and operational comparisons against the latest publicly eligible forecast. Sparse RFC output cannot establish fresh 1h/6h headline skill; operational comparisons to older forecasts remain separately labeled. Matching creation time does not prove identical internal RFC input availability.

Require target-by-month archive coverage and matched counts adjacent to metrics. Name IEM list.json entered explicitly and leave its receipt semantics unconfirmed until supported by IEM documentation or ingestion code. No external maintainer contact was made.

Restrict observed-event/background-sampled NWM comparisons to matched secondary-discharge errors; exclude FAR, recall and flood-warning claims for both models from that sample. Remove the generic WRF-Hydro link from the archive-existence citation; direct bucket evidence and the NOAA-hosted description remain. No scheduling or scope changes were made.

## Local host authorization — September 14, 2026

The local implementation may use Python 3.14 instead of the plan's original Python 3.12 baseline. Compatibility is verified by the automated test suite and containerized services retain their individually pinned runtimes. The project is authorized to retain up to 35 GB locally; acquisition must still stop before project usage exceeds that limit or host free space drops below 20 GB.

## Stage-only product scope — September 15, 2026

Numerical flood-chance prediction is removed from the product. HydroPulse forecasts gauge height, maximum gauge height, uncertainty intervals, and separate discharge. Official action/minor/moderate/major stages may appear only as reference lines and deterministic predicted-height crossing context. The application does not infer inundation, issue warnings, or ask users to interpret an unsupported probability. Historical probability eligibility audits remain research provenance explaining this decision, not a serving feature.
