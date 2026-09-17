"""Kafka event contract shared by the live collector and Spark consumer.

Kafka/Spark delivery is at-least-once.  PostgreSQL's revision identity remains
the durable idempotency boundary, so replayed Kafka messages cannot duplicate
an observation revision.
"""

from __future__ import annotations

import json
from typing import Any

from hydropulse.config import get_settings
from hydropulse.domain import Observation

OBSERVATIONS_TOPIC = "observations"


def observation_event(observation: Observation, raw_payload: dict[str, Any]) -> dict[str, Any]:
    """Build the versioned, JSON-safe event consumed by Structured Streaming."""
    return {
        "schema_version": 1,
        "event_type": "observation_revision",
        "observation": observation.model_dump(mode="json"),
        "raw_payload": raw_payload,
    }


def decode_observation_event(value: str | bytes) -> tuple[Observation, dict[str, Any]]:
    """Validate an event before it reaches the canonical ingestion transaction."""
    payload = json.loads(value)
    if payload.get("schema_version") != 1 or payload.get("event_type") != "observation_revision":
        raise ValueError("unsupported Kafka observation event")
    raw_payload = payload.get("raw_payload")
    if not isinstance(raw_payload, dict):
        raise ValueError("Kafka observation event has no raw payload object")
    return Observation.model_validate(payload["observation"]), raw_payload


def publish_observations(observations: list[Observation], raw_payload: dict[str, Any]) -> int:
    """Publish a keyed batch and wait for broker acknowledgement.

    Importing the client here keeps the direct installation free of Kafka
    dependencies.  The streaming Docker profile installs the ``stream`` extra.
    """
    if not observations:
        return 0
    try:
        from kafka import KafkaProducer
    except ImportError as exc:  # pragma: no cover - requires streaming profile
        raise RuntimeError("Kafka support requires installation with the stream extra") from exc
    producer = KafkaProducer(
        bootstrap_servers=get_settings().kafka_bootstrap_servers,
        acks="all",
        key_serializer=lambda key: key.encode(),
        value_serializer=lambda event: json.dumps(event, separators=(",", ":")).encode(),
    )
    try:
        for observation in observations:
            producer.send(OBSERVATIONS_TOPIC, key=observation.gauge_id, value=observation_event(observation, raw_payload)).get(
                timeout=30
            )
        producer.flush(timeout=30)
    finally:
        producer.close(timeout=10)
    return len(observations)
