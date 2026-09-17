"""One idempotent live collection and candidate-forecast shadow cycle."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

from hydropulse.config import get_settings
from hydropulse.db import Repository
from hydropulse.domain import BASINS
from hydropulse.forecasting import RidgeStageForecaster
from hydropulse.stage1 import collect_live


def run() -> dict:
    collection = asyncio.run(collect_live())
    repository = Repository()
    issued_at = datetime.now(UTC)
    forecasts = []
    for basin in BASINS:
        history = repository.observations(basin.usgs_id, issued_at - timedelta(hours=3), limit=1000)
        forecast = RidgeStageForecaster(
            get_settings().artifact_dir / "models" / f"stage-ridge-{basin.usgs_id}.json"
        ).predict(basin, history, issued_at, get_settings().ingestion_mode)
        repository.save_forecast(forecast)
        forecasts.append(
            {
                "target_id": basin.usgs_id,
                "forecast_id": forecast.id,
                "newest_observation_at": forecast.newest_observation_at.isoformat(),
                "freshness": forecast.freshness,
            }
        )
    return {"issued_at": issued_at.isoformat(), "collection": collection, "forecasts": forecasts}


def main() -> None:
    print(json.dumps(run(), indent=2, default=str))


if __name__ == "__main__":
    main()
