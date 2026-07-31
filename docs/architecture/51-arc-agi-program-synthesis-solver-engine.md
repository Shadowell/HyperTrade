# 51. ARC-AGI-3 (ARC Prize 2026) Program Synthesis & Grid DSL Solver Engine Architecture

## 1. Executive Summary

This specification defines the **ARC-AGI-3 (ARC Prize 2026) Solver Module Extension**.

By leveraging HyperTrade's MCTS search, AST program mutation, and self-healing harness scaffolding, this subsystem adapts our core reasoning engine to solve 2D grid abstraction and visual reasoning tasks defined in François Chollet's ARC-AGI benchmark.

```
+---------------------------------------------------------------------------------------+
|                       ARC-AGI-3 Program Synthesis Architecture                        |
+---------------------------------------------------------------------------------------+
|  1. Grid DSL Operators        |  2. MCTS Grid Solver          |  3. Exact Match Evaluator|
|  - Rotate, flip, crop, fill   |  - Searches Program Synthesis |  - 100% pixel match on   |
|  - Connected components, diff |    candidates via MCTS        |    input/output grid examples|
+---------------------------------------------------------------------------------------+
```

---

## 2. Component Design

### 2.1 `GridDSL` (2D Grid Operators)
Located in `backend/src/hypertrade/arc_agi/dsl.py`:
* **`rotate_90(grid: list[list[int]]) -> list[list[int]]`**: Rotates 2D matrix 90 degrees clockwise.
* **`flip_horizontal(grid: list[list[int]]) -> list[list[int]]`**: Flips matrix horizontally.
* **`replace_color(grid: list[list[int]], old_color: int, new_color: int) -> list[list[int]]`**: Replaces pixel color value.
* **`crop_bounding_box(grid: list[list[int]], color: int) -> list[list[int]]`**: Crops minimal bounding box containing non-zero color pixels.

### 2.2 `ARCAGIProgramSynthesisSolver`
Located in `backend/src/hypertrade/arc_agi/solver.py`:
* **`solve_task(train_examples: list[dict[str, Any]], test_input: list[list[int]]) -> list[list[int]] | None`**: Uses MCTS program search across DSL combinations, validating candidate programs against all training examples until an exact 100% pixel match program is discovered, then executes it on `test_input`.

---

## 3. Verification Plan

1. **Unit Tests (`tests/test_arc_agi_solver.py`)**:
   * Test 2D Grid DSL transformations (rotation, color replacement, cropping).
   * Test MCTS program synthesis on sample ARC-AGI grid transformation tasks.
2. **Integration Verification**:
   * Run full `./scripts/check.sh` suite ensuring 100% green test passing status across all 840+ test suites.
