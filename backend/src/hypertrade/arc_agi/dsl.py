"""
2D Grid Domain Specific Language (DSL) Operators for ARC-AGI-3 (ARC Prize 2026)
"""


class GridDSL:
    """
    DSL Operator Primitives for 2D Grid Transformation in ARC-AGI Tasks.
    """

    @staticmethod
    def rotate_90(grid: list[list[int]]) -> list[list[int]]:
        """Rotates grid 90 degrees clockwise."""
        if not grid or not grid[0]:
            return grid
        rows, cols = len(grid), len(grid[0])
        res = [[0] * rows for _ in range(cols)]
        for r in range(rows):
            for c in range(cols):
                res[c][rows - 1 - r] = grid[r][c]
        return res

    @staticmethod
    def flip_horizontal(grid: list[list[int]]) -> list[list[int]]:
        """Flips grid horizontally."""
        return [list(reversed(row)) for row in grid]

    @staticmethod
    def replace_color(
        grid: list[list[int]], old_color: int, new_color: int
    ) -> list[list[int]]:
        """Replaces all occurrences of old_color with new_color."""
        return [
            [new_color if val == old_color else val for val in row] for row in grid
        ]

    @staticmethod
    def crop_bounding_box(grid: list[list[int]], bg_color: int = 0) -> list[list[int]]:
        """Crops minimal bounding box containing non-bg_color pixels."""
        if not grid or not grid[0]:
            return grid
        rows, cols = len(grid), len(grid[0])
        min_r, max_r = rows, -1
        min_c, max_c = cols, -1

        for r in range(rows):
            for c in range(cols):
                if grid[r][c] != bg_color:
                    min_r = min(min_r, r)
                    max_r = max(max_r, r)
                    min_c = min(min_c, c)
                    max_c = max(max_c, c)

        if max_r == -1:
            return grid

        return [
            [grid[r][c] for c in range(min_c, max_c + 1)]
            for r in range(min_r, max_r + 1)
        ]

    @staticmethod
    def match_grids(
        predicted: list[list[int]], target: list[list[int]]
    ) -> bool:
        """Checks exact 100% pixel equality between predicted and target grid."""
        if len(predicted) != len(target):
            return False
        return all(predicted[r] == target[r] for r in range(len(predicted)))
