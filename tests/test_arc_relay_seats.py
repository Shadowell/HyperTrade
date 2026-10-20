"""BitPro variant-slot facts used by the evolution scan and the AVO proposal check."""

import pytest
from hypertrade.arc.relay_seats import (
    describe_tried,
    relay_seats,
    tried_variant,
    variant_identity,
)


def test_open_seats_are_the_free_ones_queued_candidates_do_not_take():
    slots = {"total": 3, "used": 1, "free": 2, "queued": 1}
    assert relay_seats({"slots": slots}) == {**slots, "open": 1}
    assert relay_seats({"slots": {**slots, "queued": 5}})["open"] == 0  # never negative
    assert relay_seats({"slots": {"total": 3, "used": 0, "free": 3, "queued": 0}})["open"] == 3


def test_a_bitpro_that_does_not_count_queued_candidates_leaves_every_free_seat_open():
    seats = relay_seats({"slots": {"total": 3, "used": 1, "free": 2}})
    assert seats == {"total": 3, "used": 1, "free": 2, "queued": 0, "open": 2}


@pytest.mark.parametrize(
    "relay",
    [
        None,
        {},
        {"slots": None},
        {"slots": {"total": 3}},
        {"slots": {"total": True, "used": 0, "free": 1}},
        {"slots": {"total": 3, "used": -1, "free": 2}},
        {"slots": {"total": "3", "used": 1, "free": 2}},
    ],
)
def test_missing_or_malformed_seats_are_unknown_not_zero(relay):
    assert relay_seats(relay) is None


def test_variant_identity_ignores_key_order_and_integral_floats_only():
    base = variant_identity({"fast_window": 8, "slow_window": 25}, None)
    assert base == variant_identity({"slow_window": 25, "fast_window": 8.0}, {})
    assert base != variant_identity({"fast_window": 8, "slow_window": 26}, {})
    assert base != variant_identity({"fast_window": 8.5, "slow_window": 25}, {})
    assert variant_identity({"threshold": 0.02}, {}) == variant_identity({"threshold": 0.02}, None)
    structural = {"volatility_filter": {"window": 14.0, "min_percentile": 0.3}}
    assert variant_identity({}, structural) == variant_identity(
        {}, {"volatility_filter": {"min_percentile": 0.3, "window": 14}}
    )
    assert variant_identity({"fast_window": 8}, {}) != variant_identity({}, {"fast_window": 8})


def test_tried_variant_finds_exactly_the_same_changes():
    relay = {
        "tried_variants": [
            {
                "candidate_strategy_id": 9,
                "state": "eliminated",
                "kind": "futility",
                "parameter_changes": {"fast_window": 9},
                "structural_changes": {},
            },
            {
                "candidate_strategy_id": 7,
                "state": "racing",
                "kind": None,
                "parameter_changes": {"fast_window": 7.0},
                "structural_changes": {},
            },
            "garbage",
        ]
    }
    assert tried_variant(relay, {"fast_window": 7}, {})["candidate_strategy_id"] == 7
    assert tried_variant(relay, {"fast_window": 9}, None)["state"] == "eliminated"
    assert tried_variant(relay, {"fast_window": 8}, {}) is None
    assert tried_variant(relay, {"fast_window": 7}, {"volatility_filter": {"window": 14}}) is None
    # Nothing is known when BitPro lists nothing (older BitPro): nothing is rejected.
    for unknown in (None, {}, {"tried_variants": None}, {"tried_variants": "x"}):
        assert tried_variant(unknown, {"fast_window": 7}, {}) is None


def test_describe_tried_names_the_variant_and_what_happened_to_it():
    assert describe_tried(
        {"candidate_strategy_id": 9, "state": "eliminated", "kind": "futility"}
    ) == "variant #9 was eliminated (futility)"
    assert describe_tried({"candidate_strategy_id": 7, "state": "waiting", "kind": None}) == (
        "variant #7 is queued for a seat"
    )
    assert describe_tried({"candidate_strategy_id": 3, "state": "new-state"}) == (
        "variant #3 was already tried"
    )
