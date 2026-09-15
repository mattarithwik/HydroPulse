from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from hydropulse.config import Settings, get_settings
from hydropulse.db import EventRow, Repository, initialize, session_scope
from hydropulse.domain import BASINS, Basin, Forecast, Observation
from hydropulse.forecasting import PersistenceForecaster, StaleObservationError

app = FastAPI(
    title="HydroPulse API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
repository = Repository()


@app.on_event("startup")
def startup() -> None:
    initialize()


def basin_for(identifier: str) -> Basin:
    for basin in BASINS:
        if identifier in {basin.slug, basin.usgs_id, basin.nwps_id}:
            return basin
    raise HTTPException(404, "unknown gauge or basin")


def operator(
    settings: Annotated[Settings, Depends(get_settings)], authorization: str | None = Header(None)
) -> None:
    if authorization != f"Bearer {settings.operator_token}":
        raise HTTPException(401, "valid local operator token required")


@app.get("/api/v1/basins", response_model=list[Basin])
def basins() -> tuple[Basin, ...]:
    return BASINS


@app.get("/api/v1/gauges", response_model=list[Basin])
def gauges() -> tuple[Basin, ...]:
    return BASINS


@app.get("/api/v1/gauges/{identifier}", response_model=Basin)
def gauge(identifier: str) -> Basin:
    return basin_for(identifier)


@app.get("/api/v1/gauges/{identifier}/observations", response_model=list[Observation])
def observations(
    identifier: str, days: int = Query(7, ge=1, le=31), limit: int = Query(1000, ge=1, le=5000)
) -> list[Observation]:
    basin = basin_for(identifier)
    return repository.observations(basin.usgs_id, datetime.now(UTC) - timedelta(days=days), limit)


@app.get("/api/v1/gauges/{identifier}/forecast/latest", response_model=Forecast)
def latest_forecast(identifier: str) -> Forecast:
    basin = basin_for(identifier)
    forecast = repository.latest_forecast(basin.usgs_id)
    if not forecast:
        raise HTTPException(404, "no forecast has been issued")
    return forecast


@app.get("/api/v1/forecasts/{forecast_id}", response_model=Forecast)
def forecast(forecast_id: str) -> Forecast:
    found = repository.forecast(forecast_id)
    if not found:
        raise HTTPException(404, "forecast not found")
    return found


@app.get("/api/v1/official-forecasts")
def official_forecasts() -> dict:
    return {
        "items": [],
        "availability_semantics": "first_seen live; assumed dissemination for historical records",
    }


@app.get("/api/v1/risk-events")
def risk_events() -> dict:
    return {
        "items": [],
        "note": "Only observed flooding and predicted stage-threshold crossings are produced; probability events are disabled.",
    }


@app.get("/api/v1/models")
def models() -> dict:
    return {
        "champion": "persistence-damped-v1",
        "stage": "available",
        "probability_products": "disabled",
    }


@app.get("/api/v1/verification")
def verification() -> dict:
    return {"status": "unscored", "independent_test_opened": False, "claims": []}


@app.get("/api/v1/system/status")
def system_status(settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    return {
        "status": "ok",
        "mode": settings.ingestion_mode,
        "targets": len(BASINS),
        "disk_budget_gb": settings.project_disk_budget_gb,
    }


@app.post(
    "/api/v1/operator/forecast/{identifier}",
    dependencies=[Depends(operator)],
    response_model=Forecast,
)
def issue_forecast(identifier: str, issued_at: datetime | None = None) -> Forecast:
    basin = basin_for(identifier)
    issued_at = issued_at or datetime.now(UTC)
    history = repository.observations(basin.usgs_id, issued_at - timedelta(days=8), 5000)
    try:
        result = PersistenceForecaster().predict(
            basin, history, issued_at, get_settings().ingestion_mode
        )
    except StaleObservationError as exc:
        raise HTTPException(409, str(exc)) from exc
    repository.save_forecast(result)
    return result


@app.get("/api/v1/events/stream")
async def event_stream(after: int = 0) -> StreamingResponse:
    async def generate():
        cursor = after
        while True:
            # Durable polling is the recovery path; PostgreSQL LISTEN/NOTIFY can wake this in production.
            with session_scope() as session:
                rows = (
                    session.query(EventRow)
                    .filter(EventRow.sequence > cursor)
                    .order_by(EventRow.sequence)
                    .limit(100)
                    .all()
                )
                for row in rows:
                    cursor = row.sequence
                    yield f"id: {cursor}\nevent: {row.event_type}\ndata: {json.dumps(row.payload)}\n\n"
            yield ": heartbeat\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(generate(), media_type="text/event-stream")
