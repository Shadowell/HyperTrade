"""
Tool Result LRU Cache & Prompt Cache Prefix Aligner Subsystem

Provides MD5-keyed TTL result caching for read-only tools and KV prompt prefix alignment.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from hypertrade.agent.harness_v2 import READ_ONLY_TOOL_NAMES

logger = logging.getLogger(__name__)


class ToolResultLRUCache:
    """
    MD5-keyed LRU cache for read-only tool results with TTL expiration.
    Automatically invalidates entries when state-modifying write operations occur.
    """

    def __init__(self, max_size: int = 256, default_ttl_sec: float = 15.0) -> None:
        self.max_size = max_size
        self.default_ttl_sec = default_ttl_sec
        # cache_key -> (timestamp, result_dict, tool_name, ttl_sec)
        self._store: dict[str, tuple[float, dict[str, Any], str, float]] = {}

    def _compute_key(self, tool_name: str, args: dict[str, Any]) -> str:
        canonical_args = json.dumps(args, sort_keys=True, separators=(",", ":"))
        raw = f"{tool_name}:{canonical_args}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def get(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any] | None:
        if tool_name not in READ_ONLY_TOOL_NAMES:
            return None

        key = self._compute_key(tool_name, args)
        entry = self._store.get(key)
        if not entry:
            return None

        created_at, res, _, ttl = entry
        if time.monotonic() - created_at > ttl:
            del self._store[key]
            return None

        logger.debug("ToolResultLRUCache HIT for tool '%s'", tool_name)
        return res

    def put(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        ttl_sec: float | None = None,
    ) -> None:
        if tool_name not in READ_ONLY_TOOL_NAMES:
            return

        if len(self._store) >= self.max_size:
            # Evict oldest entry
            oldest_key = min(self._store.keys(), key=lambda k: self._store[k][0])
            del self._store[oldest_key]

        key = self._compute_key(tool_name, args)
        ttl = ttl_sec if ttl_sec is not None else self.default_ttl_sec
        self._store[key] = (time.monotonic(), result, tool_name, ttl)

    def invalidate_on_write(self, write_tool_name: str) -> None:
        """
        Clears cached entries when a write tool modifies domain state.
        """
        self._store.clear()
        logger.debug(
            "ToolResultLRUCache invalidated all entries due to write tool '%s'",
            write_tool_name,
        )


class PromptCachePrefixAligner:
    """
    KV Prompt Cache Prefix Aligner ensuring System Prompt, System Rules,
    and Tool Schemas stay strictly at index 0 with deterministic formatting.
    """

    @staticmethod
    def align_prompt_prefix(
        system_prompt: str,
        rules: list[str],
        tools_schema: list[dict[str, Any]],
        dynamic_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        # Format immutable prefix block
        rules_text = "\n".join(f"- {r}" for r in rules)
        tools_json = json.dumps(tools_schema, sort_keys=True, indent=2)

        prefix_system_content = (
            f"{system_prompt.strip()}\n\n"
            f"### SYSTEM RULES\n{rules_text}\n\n"
            f"### AVAILABLE TOOL SCHEMAS\n{tools_json}"
        )

        system_message = {"role": "system", "content": prefix_system_content}
        return [system_message, *dynamic_messages]
