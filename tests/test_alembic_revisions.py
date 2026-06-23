from __future__ import annotations

import ast
from pathlib import Path

ALEMBIC_VERSION_NUM_LIMIT = 32


def test_alembic_revision_ids_fit_version_table() -> None:
    versions_dir = Path(__file__).resolve().parents[1] / "backend" / "alembic" / "versions"
    for path in sorted(versions_dir.glob("*.py")):
        tree = ast.parse(path.read_text())
        values: dict[str, object] = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                values[target.id] = ast.literal_eval(node.value)

        for field in ("revision", "down_revision"):
            value = values.get(field)
            revisions = value if isinstance(value, tuple) else (value,)
            for revision in revisions:
                if revision is None:
                    continue
                assert isinstance(revision, str)
                assert len(revision) <= ALEMBIC_VERSION_NUM_LIMIT, (
                    f"{path.name} {field}={revision!r} exceeds "
                    f"{ALEMBIC_VERSION_NUM_LIMIT} chars"
                )
