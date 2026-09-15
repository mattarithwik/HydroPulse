from datetime import date

from hydropulse.domain import BASINS
from hydropulse.upstream_audit import _series_by_station, lean_selection, select_candidates


def test_only_primary_instantaneous_series_are_selected():
    payload = {
        "features": [
            {
                "properties": {
                    "id": "good",
                    "monitoring_location_id": "USGS-1",
                    "parameter_code": "00065",
                    "statistic_id": "00011",
                    "primary": "Primary",
                    "computation_period_identifier": "Points",
                    "begin": "2010-01-01T00:00:00Z",
                    "end": "2026-01-01T00:00:00Z",
                }
            },
            {
                "properties": {
                    "id": "daily",
                    "monitoring_location_id": "USGS-1",
                    "parameter_code": "00065",
                    "statistic_id": "00003",
                    "primary": "Primary",
                    "computation_period_identifier": "Daily",
                    "begin": "2010-01-01T00:00:00Z",
                    "end": "2026-01-01T00:00:00Z",
                }
            },
        ]
    }
    assert _series_by_station([payload])["1"]["00065"]["id"] == "good"


def test_target_is_never_selected_as_its_own_upstream_input():
    basin = BASINS[0]
    features = [
        {
            "properties": {
                "identifier": f"USGS-{basin.usgs_id}",
                "name": "target",
                "mainstem": "m",
                "comid": 1,
            }
        },
        {"properties": {"identifier": "USGS-1", "name": "upstream", "mainstem": "m", "comid": 2}},
    ]
    series = {
        "1": {
            "00065": {
                "id": "series",
                "begin": "2007-10-01T00:00:00Z",
                "end": "2026-09-13T00:00:00Z",
            }
        }
    }
    _, selected = select_candidates(basin, features, series, date(2007, 10, 1), date(2026, 9, 13))
    assert [item.gauge_id for item in selected] == ["1"]


def test_lean_selection_keeps_three_mainstem_and_one_supplemental():
    selected = [{"gauge_id": str(index), "is_target_mainstem": index < 5} for index in range(8)]
    assert [item["gauge_id"] for item in lean_selection("target", selected)] == ["0", "1", "2", "5"]
