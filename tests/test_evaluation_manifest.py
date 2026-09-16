import json
from datetime import date

import pytest

from hydropulse.evaluation_manifest import freeze


def test_freeze_is_write_once_and_records_lags(tmp_path):
    quality = tmp_path / "quality.json"
    upstream = tmp_path / "upstream.json"
    output = tmp_path / "manifest.json"
    quality.write_text('{"generated_at":"2026-09-16T00:00:00+00:00"}')
    upstream.write_text(
        '{"archive_cutoff":"2026-09-13","targets":{"target":{"gauges":['
        '{"gauge_id":"upstream","suitable":true,"lag_sweep":{"selected":{"lag_hours":12}}}'
        "]}}}"
    )
    freeze(date(2026, 9, 13), quality, upstream, output)
    assert json.loads(output.read_text())["upstream"]["target"] == [
        {"gauge_id": "upstream", "lag_hours": 12}
    ]
    with pytest.raises(FileExistsError):
        freeze(date(2026, 9, 13), quality, upstream, output)
