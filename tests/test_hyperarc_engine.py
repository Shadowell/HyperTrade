"""
Unit & Integration Tests for HyperARC Program Synthesis Engine
"""

from hypertrade.hyperarc.solver import HyperARCSolver


def test_hyperarc_solver_rotation():
    solver = HyperARCSolver(parallel_workers=2)

    # Input: 2x2 grid [[1, 0], [0, 0]]
    # Rotated 90 deg: [[0, 1], [0, 0]]
    train_examples = [
        {
            "input": [[1, 0], [0, 0]],
            "output": [[0, 1], [0, 0]],
        }
    ]
    test_input = [[1, 1], [0, 0]]

    solved_grid = solver.solve(train_examples, test_input)
    assert solved_grid == [[0, 1], [0, 1]]
