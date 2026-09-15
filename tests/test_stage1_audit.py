from datetime import UTC, datetime

from hydropulse.stage1 import Episode, cluster_episodes


def test_cross_basin_episodes_with_overlapping_expanded_windows_are_one_storm():
    first = Episode(
        "a", datetime(2024, 1, 10, tzinfo=UTC), datetime(2024, 1, 11, tzinfo=UTC), 20, False
    )
    second = Episode(
        "b", datetime(2024, 1, 15, tzinfo=UTC), datetime(2024, 1, 16, tzinfo=UTC), 21, False
    )
    clusters = cluster_episodes([first, second])
    assert len(clusters) == 1
    assert clusters[0].gauge_ids == ("a", "b")
    assert clusters[0].episode_count == 2
