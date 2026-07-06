"""CLI output renderer with enhanced UI."""

from __future__ import annotations

import sys
from typing import Any, TextIO

from hypertrade.ui.colors import Color
from hypertrade.ui.formatter import EnhancedFormatter


def render_agent_output(
    run: dict[str, Any],
    *,
    output: TextIO | None = None,
) -> None:
    """Render agent run output with enhanced formatting.

    Args:
        run: Agent run data
        output: Output stream
    """
    output = output or sys.stdout
    formatter = EnhancedFormatter(output=output, width=80)
    color = Color(output=output)

    # Extract data
    final_answer = run.get("final_answer", "")
    status = run.get("status", "unknown")
    tool_calls = run.get("tool_calls", [])
    trace_events = run.get("trace_events", [])

    # Render header
    formatter.banner(
        "HyperTrade Agent",
        subtitle=f"Run ID: {run.get('id', 'unknown')}",
    )

    # Status
    if status == "completed":
        formatter.success(f"✓ 任务完成")
    elif status == "failed":
        formatter.error(f"✗ 任务失败")
    else:
        formatter.info(f"状态: {status}")

    print("", file=output)

    # Tool calls summary
    if tool_calls:
        formatter.section("工具调用")
        for i, tool_call in enumerate(tool_calls, 1):
            tool_name = tool_call.get("tool_name", "unknown")
            tool_status = tool_call.get("status", "unknown")

            if tool_status == "success":
                status_icon = color.success("✓")
            elif tool_status == "denied":
                status_icon = color.warning("⚠")
            else:
                status_icon = color.error("✗")

            print(f"  {i}. {status_icon} {tool_name} - {tool_status}", file=output)

        print("", file=output)

    # Final answer
    if final_answer:
        formatter.section("分析结果")
        print("", file=output)

        # Parse and render the answer
        _render_markdown_enhanced(final_answer, formatter=formatter, color=color, output=output)

    # Footer
    formatter.divider()
    formatter.timestamp()
    print("", file=output)


def _render_markdown_enhanced(
    markdown: str,
    *,
    formatter: EnhancedFormatter,
    color: Color,
    output: TextIO,
) -> None:
    """Render markdown with enhanced formatting."""
    lines = markdown.split("\n")

    in_code_block = False
    in_table = False

    for line in lines:
        # Code blocks
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue

        if in_code_block:
            print(color.paint(line, "muted"), file=output)
            continue

        # Headers
        if line.startswith("###"):
            text = line.replace("###", "").strip()
            formatter.subsection(text)
            continue
        elif line.startswith("##"):
            text = line.replace("##", "").strip()
            formatter.section(text)
            continue
        elif line.startswith("#"):
            text = line.replace("#", "").strip()
            print("", file=output)
            print(color.bold(text), file=output)
            print("", file=output)
            continue

        # Lists
        if line.strip().startswith("-") or line.strip().startswith("*"):
            text = line.strip()[1:].strip()
            # Check for status indicators
            if "✓" in text or "成功" in text:
                print(f"  • {color.success(text)}", file=output)
            elif "✗" in text or "失败" in text or "错误" in text:
                print(f"  • {color.error(text)}", file=output)
            elif "⚠" in text or "警告" in text or "注意" in text:
                print(f"  • {color.warning(text)}", file=output)
            else:
                print(f"  • {text}", file=output)
            continue

        # Tables
        if "|" in line and "---" not in line:
            # Simple table row rendering
            print(color.paint(line, "value"), file=output)
            continue

        # Bold text
        if "**" in line:
            # Highlight bold text
            parts = line.split("**")
            result = []
            for i, part in enumerate(parts):
                if i % 2 == 1:  # Bold part
                    result.append(color.bold(part))
                else:
                    result.append(part)
            print("".join(result), file=output)
            continue

        # Percentage changes
        if "%" in line and ("+" in line or "-" in line):
            # Color percentage changes
            import re
            def colorize_pct(match):
                value = match.group(0)
                try:
                    num = float(value.replace("%", "").replace("+", ""))
                    if num > 0:
                        return color.bullish(value)
                    elif num < 0:
                        return color.bearish(value)
                    else:
                        return color.neutral(value)
                except:
                    return value

            line = re.sub(r'[+-]?\d+\.?\d*%', colorize_pct, line)
            print(line, file=output)
            continue

        # Regular line
        if line.strip():
            print(line, file=output)
        else:
            print("", file=output)


def render_world_state_summary(
    world_state: dict[str, Any],
    *,
    output: TextIO | None = None,
) -> None:
    """Render world state with enhanced formatting.

    Args:
        world_state: World state data
        output: Output stream
    """
    output = output or sys.stdout
    formatter = EnhancedFormatter(output=output, width=80)
    color = Color(output=output)

    formatter.header("🌍 全球市场状态", subtitle="World State Snapshot")

    # Risk regime
    risk_regime = world_state.get("risk_regime", "unknown")
    formatter.kv("风险制度", _format_regime(risk_regime, color), indent=1)

    # Volatility regime
    volatility_regime = world_state.get("volatility_regime", "unknown")
    formatter.kv("波动率", _format_regime(volatility_regime, color), indent=1)

    # Cross-asset signal
    cross_asset = world_state.get("cross_asset_signal", "unknown")
    formatter.kv("跨资产信号", _format_signal(cross_asset, color), indent=1)

    print("", file=output)

    # Metrics
    metrics = world_state.get("metrics", {})
    if metrics:
        formatter.subsection("系统指标")
        for key, value in metrics.items():
            formatter.kv(key, value, indent=2)

    formatter.divider()


def _format_regime(regime: str, color: Color) -> str:
    """Format regime with color."""
    regime_lower = str(regime).lower()

    if regime_lower in ("bullish", "低波动", "low"):
        return color.bullish(f"✓ {regime}")
    elif regime_lower in ("bearish", "高波动", "high"):
        return color.bearish(f"✗ {regime}")
    elif regime_lower in ("mixed", "elevated", "偏高"):
        return color.warning(f"⚠ {regime}")
    else:
        return color.neutral(f"➖ {regime}")


def _format_signal(signal: str, color: Color) -> str:
    """Format signal with color."""
    signal_lower = str(signal).lower()

    if signal_lower in ("aligned", "一致"):
        return color.bullish(f"✓ {signal}")
    elif signal_lower in ("conflicting", "冲突"):
        return color.warning(f"⚡ {signal}")
    else:
        return color.neutral(f"➖ {signal}")
