import pytest

from thoth_control_plane.acquisition.normalize import (
    normalize_engagement,
    published_at_from_epoch,
)

STATS = {"playCount": 10, "diggCount": 5, "commentCount": 2, "shareCount": 1, "collectCount": 3}


def test_stats_v2_wins_per_key_and_stats_fills_the_rest() -> None:
    stats_v2 = {"playCount": "12345678901234567", "diggCount": "-1"}

    assert normalize_engagement(STATS, stats_v2) == {
        "play": 12345678901234567,
        "like": 5,
        "comment": 2,
        "share": 1,
        "collect": 3,
    }


def test_tikwm_snake_case_counters_are_recognized() -> None:
    data = {
        "play_count": 7,
        "digg_count": 6,
        "comment_count": 5,
        "share_count": 4,
        "collect_count": 3,
    }

    assert normalize_engagement(data, None) == {
        "play": 7,
        "like": 6,
        "comment": 5,
        "share": 4,
        "collect": 3,
    }


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        -1,
        1.5,
        "-3",
        "1e3",
        " 12",
        "١٢",
        "9" * 20,
        "",
        None,
        [1],
        {"n": 1},
        2**63,
        str(2**63),
        "9" * 5_000,
    ],
)
def test_invalid_counts_are_skipped_never_guessed(value: object) -> None:
    assert normalize_engagement({"playCount": value}, {"playCount": value}) == {}


@pytest.mark.parametrize("value", [2**63 - 1, str(2**63 - 1)])
def test_counts_up_to_int64_are_kept_as_json_numbers_or_strings(value: object) -> None:
    assert normalize_engagement({"playCount": value}, None) == {"play": 2**63 - 1}


@pytest.mark.parametrize("stats", [None, [], "10", 5])
def test_non_mapping_stats_yield_nothing(stats: object) -> None:
    assert normalize_engagement(stats, stats) == {}


@pytest.mark.parametrize("value", [1709287200, "1709287200"])
def test_epoch_seconds_become_iso_utc(value: object) -> None:
    assert published_at_from_epoch(value) == "2024-03-01T10:00:00Z"


@pytest.mark.parametrize(
    "value", [0, -5, True, 1709287200.5, "2024-03-01", "", None, 10**20, "9" * 30, 10**400]
)
def test_invalid_epochs_are_none(value: object) -> None:
    assert published_at_from_epoch(value) is None
