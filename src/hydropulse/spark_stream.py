"""Spark Structured Streaming consumer for canonical observation revisions.

Run only in the ``streaming`` Compose profile.  ``foreachBatch`` is
at-least-once, while ``persist_observations`` deduplicates by the immutable
source revision identity inside PostgreSQL.
"""

from __future__ import annotations

import os

from hydropulse.ingestion import persist_observations
from hydropulse.streaming import OBSERVATIONS_TOPIC, decode_observation_event


def persist_batch(batch, batch_id: int) -> None:
    """Validate then persist one micro-batch through the shared transaction."""
    grouped: dict[str, tuple[list, dict]] = {}
    for row in batch.select("value").toLocalIterator():
        observation, raw_payload = decode_observation_event(row.value)
        key = observation.raw_payload_hash
        observations, _ = grouped.setdefault(key, ([], raw_payload))
        observations.append(observation)
    for observations, raw_payload in grouped.values():
        persist_observations(observations, raw_payload)


def main() -> None:
    from pyspark.sql import SparkSession

    bootstrap = os.environ.get("HYDROPULSE_KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    checkpoint = os.environ.get("HYDROPULSE_SPARK_CHECKPOINT", "/app/data/spark-checkpoints/observations")
    spark = SparkSession.builder.appName("hydropulse-observation-stream").getOrCreate()
    source = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap)
        .option("subscribe", OBSERVATIONS_TOPIC)
        .option("startingOffsets", "latest")
        .load()
        .selectExpr("CAST(value AS STRING) AS value")
    )
    query = (
        source.writeStream.foreachBatch(persist_batch)
        .option("checkpointLocation", checkpoint)
        .trigger(processingTime="5 minutes")
        .start()
    )
    query.awaitTermination()


if __name__ == "__main__":
    main()
