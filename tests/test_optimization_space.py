from __future__ import annotations

import random
from unittest.mock import AsyncMock

import pytest
from hypertrade.research.optimization.space import (
    CategoricalParam,
    ConstraintRule,
    FloatParam,
    GridSampler,
    IntParam,
    LlmMutationSampler,
    ParameterSpace,
    RandomSampler,
    extract_parameter_space_from_code,
)


def test_int_param_lifecycle() -> None:
    param = IntParam(name="window", min_val=5, max_val=25, step=5, default=15)
    rng = random.Random(42)

    # Validate value
    assert param.validate_value(5)
    assert param.validate_value(15)
    assert not param.validate_value(7)
    assert not param.validate_value(30)
    assert not param.validate_value("15")

    # Grid
    grid = param.grid()
    assert grid == [5, 10, 15, 20, 25]

    # Sample
    sample = param.sample(rng)
    assert sample in grid

    # Perturb
    perturbed = param.perturb(15, ratio=0.5, rng=rng)
    assert perturbed in grid
    assert 5 <= perturbed <= 25

    # Dict roundtrip
    d = param.to_dict()
    restored = IntParam.from_dict(d)
    assert restored == param


def test_float_param_lifecycle() -> None:
    param = FloatParam(name="stop_loss", min_val=0.01, max_val=0.05, step=0.01, default=0.02)
    rng = random.Random(42)

    assert param.validate_value(0.02)
    assert param.validate_value(0.05)
    assert not param.validate_value(0.06)

    grid = param.grid(points=5)
    assert len(grid) == 5
    assert grid[0] == 0.01
    assert grid[-1] == 0.05

    sample = param.sample(rng)
    assert 0.01 <= sample <= 0.05

    d = param.to_dict()
    restored = FloatParam.from_dict(d)
    assert restored.name == param.name
    assert restored.min_val == param.min_val


def test_categorical_param_lifecycle() -> None:
    param = CategoricalParam(name="ma_type", choices=["SMA", "EMA", "WMA"], default="EMA")
    rng = random.Random(42)

    assert param.validate_value("EMA")
    assert not param.validate_value("HMA")

    grid = param.grid()
    assert grid == ["SMA", "EMA", "WMA"]

    sample = param.sample(rng)
    assert sample in ["SMA", "EMA", "WMA"]

    perturbed = param.perturb("EMA", ratio=0.1, rng=rng)
    assert perturbed in ["SMA", "WMA"]

    d = param.to_dict()
    restored = CategoricalParam.from_dict(d)
    assert restored.choices == param.choices


def test_parameter_space_validation_and_sampling() -> None:
    space = ParameterSpace(
        parameters=[
            IntParam("fast", 5, 20, step=5),
            IntParam("slow", 10, 50, step=10),
        ],
        constraints=[
            ConstraintRule("fast < slow"),
        ],
    )

    # Valid candidate
    valid, msg = space.validate({"fast": 5, "slow": 20})
    assert valid
    assert msg == ""

    # Invalid constraint
    valid, msg = space.validate({"fast": 20, "slow": 10})
    assert not valid
    assert "Violated constraint" in msg

    # Random sampling
    rng = random.Random(123)
    sample = space.sample_random(rng)
    assert sample["fast"] < sample["slow"]

    # Grid generation
    grid = space.generate_grid()
    assert len(grid) > 0
    for cand in grid:
        assert cand["fast"] < cand["slow"]

    # Roundtrip
    d = space.to_dict()
    restored = ParameterSpace.from_dict(d)
    assert len(restored.parameters) == 2
    assert len(restored.constraints) == 1


def test_extract_parameter_space_from_code() -> None:
    code = """
class TrendFollowStrategy:
    def __init__(
        self, fast_period: int = 10, slow_period: int = 30, stop_loss: float = 0.02
    ) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.stop_loss = stop_loss

    def on_bar(self, bar):
        threshold = config.get("vol_filter", 1.5)
"""
    space = extract_parameter_space_from_code(code)
    assert "fast_period" in space.parameters
    assert "slow_period" in space.parameters
    assert "stop_loss" in space.parameters
    assert isinstance(space.parameters["fast_period"], IntParam)
    assert isinstance(space.parameters["stop_loss"], FloatParam)

    # Check auto-added constraint
    assert any("fast_period < slow_period" in c.expression for c in space.constraints)


def test_samplers() -> None:
    space = ParameterSpace(
        parameters=[
            IntParam("p1", 1, 3, step=1),
            IntParam("p2", 10, 20, step=10),
        ]
    )

    # Grid sampler
    grid_sampler = GridSampler(space, points_per_param=3)
    all_grid = grid_sampler.sample_all()
    assert len(all_grid) == 6

    # Random sampler
    rand_sampler = RandomSampler(space, seed=77)
    random_samples = rand_sampler.sample_n(4)
    assert len(random_samples) == 4


@pytest.mark.anyio
async def test_llm_mutation_sampler_fallback() -> None:
    space = ParameterSpace(
        parameters=[
            IntParam("p1", 1, 10, step=1),
        ]
    )
    sampler = LlmMutationSampler(space, seed=99)
    # Without chat_provider
    mutations = await sampler.mutate(
        current_best={"p1": 5},
        top_trials=[],
        worst_trials=[],
        n_mutations=3,
        chat_provider=None,
    )
    assert len(mutations) == 3
    for m in mutations:
        assert "p1" in m
        assert 1 <= m["p1"] <= 10


@pytest.mark.anyio
async def test_llm_mutation_sampler_with_provider() -> None:
    space = ParameterSpace(
        parameters=[
            IntParam("fast", 5, 25, step=5),
            IntParam("slow", 30, 60, step=10),
        ],
        constraints=[ConstraintRule("fast < slow")],
    )
    sampler = LlmMutationSampler(space, seed=99)

    from unittest.mock import MagicMock

    mock_chat = MagicMock()
    mock_chat.chat = AsyncMock(
        return_value=MagicMock(
            content='```json\n[{"fast": 10, "slow": 40}, {"fast": 15, "slow": 50}]\n```'
        )
    )

    mutations = await sampler.mutate(
        current_best={"fast": 5, "slow": 30},
        top_trials=[{"parameters": {"fast": 5, "slow": 30}, "sharpe": 1.8}],
        worst_trials=[{"parameters": {"fast": 25, "slow": 30}, "sharpe": -0.5}],
        n_mutations=2,
        chat_provider=mock_chat,
    )
    assert len(mutations) == 2
    assert mutations[0] == {"fast": 10, "slow": 40}
    assert mutations[1] == {"fast": 15, "slow": 50}
