from __future__ import annotations

import json
from datetime import datetime, timedelta
from math import exp
from pathlib import Path

import numpy as np

from hydropulse.domain import (
    HORIZONS,
    QUANTILES,
    Basin,
    Forecast,
    Freshness,
    Observation,
    QuantilePoint,
    ThresholdCrossing,
    freshness_at,
    stable_id,
)


class StaleObservationError(ValueError):
    pass


class IncompatibleModelError(ValueError):
    pass


class RidgeStageForecaster:
    """Serve a frozen linear stage model with calibrated residual intervals."""

    def __init__(self, model_path: Path):
        self.model = json.loads(model_path.read_text())
        if self.model["selected_variant"] != "target_only":
            raise IncompatibleModelError("serving upstream models requires live upstream features")
        self.version = f"{self.model['model_type']}-{self.model['target_id']}"

    def predict(
        self,
        basin: Basin,
        observations: list[Observation],
        issued_at: datetime,
        mode: str = "direct",
    ) -> Forecast:
        usable = sorted(
            (o for o in observations if o.value is not None and o.event_time <= issued_at),
            key=lambda o: o.event_time,
        )
        if not usable:
            raise ValueError("at least one causal observation is required")
        latest = usable[-1]
        freshness, age = freshness_at(issued_at, latest.event_time)
        if freshness is Freshness.SUPPRESSED:
            raise StaleObservationError(f"newest observation is {age:.0f} minutes old")
        prior_candidates = [
            item
            for item in usable
            if latest.event_time - timedelta(minutes=75)
            <= item.event_time
            <= latest.event_time - timedelta(minutes=45)
        ]
        if not prior_candidates:
            raise ValueError("an observation approximately one hour earlier is required")
        prior = min(
            prior_candidates,
            key=lambda item: abs((latest.event_time - item.event_time).total_seconds() - 3600),
        )
        x = np.asarray([float(latest.value), float(latest.value - prior.value)])
        means = np.asarray(self.model["feature_means"])
        scales = np.asarray(self.model["feature_scales"])
        center = np.asarray(self.model["intercept"]) + ((x - means) / scales) @ np.asarray(
            self.model["weights"]
        )
        stage: list[QuantilePoint] = []
        maxima: list[QuantilePoint] = []
        running = {str(q): float(latest.value) for q in QUANTILES}
        for index, horizon in enumerate(HORIZONS):
            quantiles = {
                str(q): max(
                    0.0,
                    float(center[index]) + self.model["residual_quantile_offsets"][str(q)][index],
                )
                for q in QUANTILES
            }
            stage.append(
                QuantilePoint(
                    horizon_hours=horizon,
                    valid_at=issued_at + timedelta(hours=horizon),
                    quantiles=quantiles,
                )
            )
            running = {key: max(running[key], value) for key, value in quantiles.items()}
            maxima.append(
                QuantilePoint(
                    horizon_hours=horizon,
                    valid_at=issued_at + timedelta(hours=horizon),
                    quantiles=dict(running),
                )
            )
        crossings = tuple(
            ThresholdCrossing(
                threshold_name="minor",
                threshold_ft=basin.flood_stage_ft,
                horizon_hours=point.horizon_hours,
                median_crosses=point.quantiles["0.5"] >= basin.flood_stage_ft,
                forecast_interval_straddles=(
                    point.quantiles["0.05"] < basin.flood_stage_ft <= point.quantiles["0.95"]
                ),
            )
            for point in maxima
        )
        snapshot = stable_id(basin.usgs_id, issued_at.isoformat(), latest.raw_payload_hash, mode)
        reasons = ("observation age exceeds 90 minutes",) if freshness is Freshness.DEGRADED else ()
        return Forecast(
            id=stable_id(snapshot, self.version),
            target_id=basin.usgs_id,
            issued_at=issued_at,
            newest_observation_at=latest.event_time,
            observation_age_minutes=age,
            available_data_cutoff=issued_at,
            snapshot_id=snapshot,
            stage_model_version=self.version,
            discharge_model_version="unavailable",
            threshold_version="nwps-live",
            weather_provider=None,
            weather_cycle=None,
            weather_coverage=None,
            mode=mode,
            freshness=freshness,
            degradation_reasons=reasons,
            stage=tuple(stage),
            maximum_stage=tuple(maxima),
            threshold_crossings=crossings,
            horizon_model_mapping={horizon: "no-nwp-target-only" for horizon in HORIZONS},
        )


class PersistenceForecaster:
    """Transparent vertical-slice baseline with a damped local trend."""

    version = "persistence-damped-v1"

    def predict(
        self,
        basin: Basin,
        observations: list[Observation],
        issued_at: datetime,
        mode: str = "direct",
    ) -> Forecast:
        usable = sorted(
            (o for o in observations if o.value is not None and o.event_time <= issued_at),
            key=lambda o: o.event_time,
        )
        if not usable:
            raise ValueError("at least one causal observation is required")
        latest = usable[-1]
        freshness, age = freshness_at(issued_at, latest.event_time)
        if freshness is Freshness.SUPPRESSED:
            raise StaleObservationError(f"newest observation is {age:.0f} minutes old")
        recent = [o.value for o in usable if o.event_time >= issued_at - timedelta(hours=6)]
        slope = 0.0 if len(recent) < 2 else (recent[-1] - recent[0]) / max(1, len(recent) - 1)
        base = float(latest.value)
        stage: list[QuantilePoint] = []
        maxima: list[QuantilePoint] = []
        discharge: list[QuantilePoint] = []
        running_max = base
        for horizon in HORIZONS:
            point = base + slope * 6 * (1 - exp(-horizon / 6))
            running_max = max(running_max, point)
            spread = 0.08 + 0.06 * horizon**0.5
            stage.append(self._point(issued_at, horizon, point, spread))
            maxima.append(self._point(issued_at, horizon, running_max, spread * 1.15))
            q = max(0.0, 500 * max(point, 0) ** 1.5)
            discharge.append(self._point(issued_at, horizon, q, max(25, q * 0.15)))
        crossings = tuple(
            ThresholdCrossing(
                threshold_name="minor",
                threshold_ft=basin.flood_stage_ft,
                horizon_hours=h,
                median_crosses=maxima[i].quantiles["0.5"] >= basin.flood_stage_ft,
                forecast_interval_straddles=(
                    maxima[i].quantiles["0.05"]
                    < basin.flood_stage_ft
                    <= maxima[i].quantiles["0.95"]
                ),
            )
            for i, h in enumerate(HORIZONS)
        )
        snapshot = stable_id(basin.usgs_id, issued_at.isoformat(), latest.raw_payload_hash, mode)
        reasons = ("observation age exceeds 90 minutes",) if freshness is Freshness.DEGRADED else ()
        return Forecast(
            id=stable_id(snapshot, self.version),
            target_id=basin.usgs_id,
            issued_at=issued_at,
            newest_observation_at=latest.event_time,
            observation_age_minutes=age,
            available_data_cutoff=issued_at,
            snapshot_id=snapshot,
            stage_model_version=self.version,
            discharge_model_version="separate-rating-proxy-v1",
            threshold_version="nwps-live",
            weather_provider=None,
            weather_cycle=None,
            weather_coverage=None,
            mode=mode,
            freshness=freshness,
            degradation_reasons=reasons,
            stage=tuple(stage),
            maximum_stage=tuple(maxima),
            discharge=tuple(discharge),
            threshold_crossings=crossings,
            horizon_model_mapping={
                1: "no-nwp",
                6: "no-nwp",
                24: "no-nwp",
                48: "no-nwp",
                72: "no-nwp",
            },
        )

    @staticmethod
    def _point(issued_at: datetime, horizon: int, center: float, spread: float) -> QuantilePoint:
        offsets = {
            "0.05": -1.64,
            "0.1": -1.28,
            "0.25": -0.67,
            "0.5": 0,
            "0.75": 0.67,
            "0.9": 1.28,
            "0.95": 1.64,
        }
        return QuantilePoint(
            horizon_hours=horizon,
            valid_at=issued_at + timedelta(hours=horizon),
            quantiles={q: max(0.0, center + z * spread) for q, z in offsets.items()},
        )
