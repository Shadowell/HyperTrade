"""Which build is running: package version plus the commit SHA stamped into the release tree.

The SHA lives in ``BUILD_INFO`` next to this module. In the repository the file holds the
placeholder ``$Format:%H$``; ``.gitattributes`` marks it ``export-subst`` so ``git archive``
(used by the hosted deploy) replaces it with the archived commit, and the self-hosted deploy
workflow writes ``$GITHUB_SHA`` into it before syncing the release. A plain checkout therefore
reports ``sha: null`` instead of claiming to be some commit, and a deploy can compare what the
site reports with the commit it meant to ship.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
from pathlib import Path

BUILD_INFO_PATH = Path(__file__).with_name("BUILD_INFO")
_SHA = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class BuildInfo:
    version: str
    sha: str | None

    def to_dict(self) -> dict[str, str | bool | None]:
        return {"version": self.version, "sha": self.sha, "stamped": self.sha is not None}


def read_sha(path: Path = BUILD_INFO_PATH) -> str | None:
    """The stamped commit SHA, or ``None`` for a missing, unexpanded or malformed stamp."""
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return raw if _SHA.fullmatch(raw) else None


@lru_cache(maxsize=1)
def get_build_info() -> BuildInfo:
    try:
        version = metadata.version("hypertrade")
    except metadata.PackageNotFoundError:
        version = "unknown"
    return BuildInfo(version=version, sha=read_sha())
