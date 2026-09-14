from __future__ import annotations

from datetime import datetime, timedelta
from math import exp

from hydropulse.domain import (
    HORIZONS,
    Basin,
    EvidenceStatus,
    Forecast,
    Freshness,
    Observation,
    QuantilePoint,
    RiskEstimate,
    freshness_at,
    stable_id,
)


class StaleObservationError(ValueError):
    pass


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
        calibration = EvidenceStatus.INSUFFICIENT_EVENTS
        risks = tuple(
            RiskEstimate(
                threshold_name="minor",
                threshold_ft=basin.flood_stage_ft,
                horizon_hours=h,
                probability=self._logistic(maxima[i].quantiles["0.5"], basin.flood_stage_ft),
                method="stage_maximum_distribution_proxy",
                evidence_status=calibration,
                independent_training_clusters=0,
                independent_calibration_clusters=0,
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
            risk=risks,
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

    @staticmethod
    def _logistic(value: float, threshold: float) -> float:
        return 1 / (1 + exp(-(value - threshold) / 0.75))


def eligibility_status(
    training: int, validation: int, calibration: int, target_training: int, target_calibration: int
) -> EvidenceStatus:
    eligible = (
        training >= 30
        and validation >= 10
        and calibration >= 10
        and target_training >= 3
        and target_calibration >= 3
    )
    return EvidenceStatus.VALIDATED if eligible else EvidenceStatus.INSUFFICIENT_EVENTS


def ordered_probabilities(probabilities: list[float]) -> list[float]:
    """Project cumulative horizon risks onto a non-decreasing sequence."""
    result: list[float] = []
    for probability in probabilities:
        result.append(max(result[-1] if result else 0.0, min(1.0, max(0.0, probability))))
    return result
