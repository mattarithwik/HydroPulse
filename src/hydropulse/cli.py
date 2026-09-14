from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from hydropulse.db import ObservationRow, initialize, session_scope
from hydropulse.domain import BASINS


def seed_demo() -> None:
    """Seed clearly labeled synthetic observations for UI development only."""
    initialize()
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    with session_scope() as session:
        for basin_index, basin in enumerate(BASINS):
            for step in range(49):
                event_time = now - timedelta(minutes=15 * (48 - step))
                value = 4.0 + basin_index * 1.7 + step * 0.015
                token = f"demo:{basin.usgs_id}:{event_time.isoformat()}"
                session.merge(
                    ObservationRow(
                        source="demo",
                        time_series_id=f"demo-{basin.usgs_id}-00065",
                        gauge_id=basin.usgs_id,
                        parameter_code="00065",
                        event_time=event_time,
                        value=value,
                        unit="ft",
                        first_seen_at=event_time + timedelta(minutes=10),
                        ingested_at=event_time + timedelta(minutes=10),
                        qualifiers=["synthetic-demo"],
                        approved=False,
                        payload_hash=__import__("hashlib").sha256(token.encode()).hexdigest(),
                        raw_payload={"demo": True},
                    )
                )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init-db", "seed-demo"])
    args = parser.parse_args()
    initialize() if args.command == "init-db" else seed_demo()


if __name__ == "__main__":
    main()
