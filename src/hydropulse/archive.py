from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError

from hydropulse.config import get_settings
from hydropulse.db import SourceArchiveRow, session_scope


@dataclass(frozen=True)
class ArchivedPayload:
    content_hash: str
    relative_path: str
    byte_count: int
    created: bool


def canonical_bytes(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode()
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def archive_payload(
    source: str,
    resource: str,
    payload: Any,
    *,
    retrieved_at: datetime | None = None,
    source_modified_at: datetime | None = None,
    media_type: str = "application/json",
    metadata: dict[str, Any] | None = None,
) -> ArchivedPayload:
    """Write immutable content before recording it; retries reuse the same hash."""
    retrieved_at = retrieved_at or datetime.now(UTC)
    data = canonical_bytes(payload)
    digest = sha256(data).hexdigest()
    relative = Path("raw") / source / retrieved_at.strftime("%Y/%m/%d") / f"{digest}.gz"
    target = get_settings().data_dir / relative
    created = not target.exists()
    if created:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".gz.tmp")
        with gzip.open(temporary, "wb") as output:
            output.write(data)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    try:
        with session_scope() as session:
            session.add(
                SourceArchiveRow(
                    content_hash=digest,
                    source=source,
                    resource=resource,
                    retrieved_at=retrieved_at,
                    first_seen_at=retrieved_at,
                    source_modified_at=source_modified_at,
                    media_type=media_type,
                    byte_count=len(data),
                    relative_path=str(relative),
                    metadata_json=metadata or {},
                )
            )
    except IntegrityError:
        created = False
    return ArchivedPayload(digest, str(relative), len(data), created)
