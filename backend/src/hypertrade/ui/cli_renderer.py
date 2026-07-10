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

    # Render header
    formatter.banner(
        "HyperTrade Agent",
        subtitle=f"Run ID: {run.get('id', 'unknown')}",
    )

    # Status
    if status == "completed":
        formatter.success("✓ 任务完成")
    elif status == "failed":
        formatter.error("✗ 任务失败")
    else:
        formatter.info(f"状态: {status}")

    print("", file=output)

    # Tool calls summary
    if tool_calls:
        formatter.section("工具调用")

        success_count = 0
        denied_count = 0
        failed_count = 0

        for i, tool_call in enumerate(tool_calls, 1):
            tool_name = tool_call.get("tool_name", "unknown")
            tool_status = tool_call.get("status", "unknown")

            if tool_status == "success":
                status_icon = color.success("✓")
                success_count += 1
            elif tool_status == "denied":
                status_icon = color.warning("⚠")
                denied_count += 1
            else:
                status_icon = color.error("✗")
                failed_count += 1

            print(f"  {i}. {status_icon} {tool_name} - {tool_status}", file=output)

        print("", file=output)

        # Summary
        if denied_count > 0:
            formatter.warning(f"⚠ {denied_count} 个工具调用被拒绝 - 可能是权限限制")
            print("", file=output)
        if failed_count > 0:
            formatter.error(f"✗ {failed_count} 个工具调用失败")
            print("", file=output)

    # Final answer
    if final_answer:
        formatter.section("分析结果")
        print("", file=output)

        # Parse and render the answer
        _render_markdown_enhanced(final_answer, formatter=formatter, color=color, output=output)
    else:
        # No final answer - show helpful message
        if tool_calls and any(tc.get("status") == "denied" for tc in tool_calls):
            formatter.section("说明")
            print("", file=output)
            formatter.box(
                "由于工具调用被拒绝，Agent 无法获取数据进行分析。\n\n"
                "可能的原因：\n"
                "• 权限不足 - 需要管理员授权\n"
                "• 风险策略限制 - 当前处于只读模式\n"
                "• 配置问题 - 检查工具权限设置\n\n"
                "建议：\n"
                "1. 检查用户权限配置\n"
                "2. 联系管理员授予工具访问权限\n"
                "3. 查看风险策略设置\n"
                "4. 运行演示脚本查看完整效果：\n"
                "   uv run python scripts/demo_agent_task_complete.py",
                title="⚠️  工具访问受限",
            )
            print("", file=output)

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
    import re

    lines = markdown.split("\n")

    in_code_block = False

    for line in lines:
        # Code blocks
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue

        if in_code_block:
            print(color.paint(line, "muted"), file=output)
            continue

        # Horizontal rule (---, ***, ___)
        if _is_horizontal_rule(line):
            formatter.divider()
            continue

        # Headers — use slice to avoid greedy replace of # characters
        if line.startswith("###"):
            text = line[3:].strip()
            formatter.subsection(text)
            continue
        elif line.startswith("##"):
            text = line[2:].strip()
            formatter.section(text)
            continue
        elif line.startswith("#"):
            text = line[1:].strip()
            print("", file=output)
            print(color.bold(text), file=output)
            print("", file=output)
            continue

        # Bullet list items (- or * followed by a space, but not **bold** markers)
        if _is_bullet_list_item(line):
            text = line.strip()[1:].strip()
            text = _apply_inline_formatting(text, color)
            _print_status_list_item(text, color=color, output=output)
            continue

        # Ordered list items (1., 2., ...)
        if _is_ordered_list_item(line):
            m = re.match(r"^(\d+)\.[ \t]+", line.strip())
            if m:
                num_str = m.group(1) + "."
                text = line.strip()[m.end():].strip()
            else:
                num_str = "•"
                text = line.strip()
            text = _apply_inline_formatting(text, color)
            _print_status_list_item(text, color=color, output=output, bullet=num_str)
            continue

        # Pipe-delimited table rows — render with full column alignment
        if _is_table_row(line):
            print(_apply_inline_formatting(line.strip(), color), file=output)
            continue

        # Table separator line (skip, but print a thin divider for visual separation)
        if _is_table_separator(line):
            print(color.paint("  " + "─" * (formatter.width - 4), "border"), file=output)
            continue

        # Regular line — apply inline formatting (bold + percentage color)
        line_stripped = line.strip()
        if line_stripped:
            print(_apply_inline_formatting(line_stripped, color), file=output)
        else:
            print("", file=output)


def _is_horizontal_rule(line: str) -> bool:
    """Check if a line is a markdown horizontal rule (---, ***, ___).

    Matches 3+ consecutive identical characters from the set -*_,
    optionally with up to 2 spaces between characters.
    """
    stripped = line.strip()
    if len(stripped) < 3:
        return False
    # All same char from the hr set
    if all(c == stripped[0] for c in stripped) and stripped[0] in "-*_":
        return True
    # Spaced variant: "- - -"
    return bool(
        len(stripped) >= 5
        and stripped[0] in "-*_"
        and all(c == stripped[0] or c == " " for c in stripped)
        and sum(1 for c in stripped if c == stripped[0]) >= 3
    )


def _is_bullet_list_item(line: str) -> bool:
    """Check if line is a bullet list item (- or * followed by a space).

    Excludes **bold** text, horizontal rules, and *** separators.
    """
    stripped = line.strip()
    if _is_horizontal_rule(line):
        return False
    if not (stripped.startswith("- ") or stripped.startswith("* ")):
        return False
    # Exclude **bold text** which also starts with *
    return not (stripped.startswith("**") and stripped.count("**") >= 2)


def _is_ordered_list_item(line: str) -> bool:
    """Check if a line is an ordered list item (e.g. '1. text', '10. text')."""
    import re

    return bool(re.match(r"^\d+\.[ \t]", line.strip()))


def _is_table_row(line: str) -> bool:
    """Check if a line is a markdown table data/header row (contains | but not --- separator)."""
    stripped = line.strip()
    return "|" in stripped and not _is_table_separator(line)


def _is_table_separator(line: str) -> bool:
    """Check if a line is a markdown table separator (e.g. |---|---|).

    We've already excluded horizontal rules at this point, so
    anything containing | that reduces to only dashes is a table separator.
    """
    stripped = line.strip()
    if "|" not in stripped:
        return False
    # Remove pipes, whitespace, and colons — what remains should be only dashes
    cleaned = (
        stripped.replace("|", "")
        .replace(" ", "")
        .replace("\t", "")
        .replace(":", "")
    )
    return len(cleaned) >= 3 and all(c == "-" for c in cleaned)


def _apply_inline_formatting(line: str, color: Color) -> str:
    """Apply bold and percentage colorization to a line in one pass.

    Bold markers (**) are processed first; percentage values inside
    both bold and non-bold spans are colorized (green/red/yellow).
    """
    if "**" in line:
        parts = line.split("**")
        result = []
        for i, part in enumerate(parts):
            if i % 2 == 1:  # Bold span
                result.append(color.bold(_colorize_percentages(part, color)))
            else:
                result.append(_colorize_percentages(part, color))
        return "".join(result)
    else:
        return _colorize_percentages(line, color)


def _colorize_percentages(text: str, color: Color) -> str:
    """Colorize signed percentage values with bullish/bearish/neutral colors."""
    import re

    def _replace(match: re.Match[str]) -> str:
        value = match.group(0)
        try:
            num = float(value.replace("%", "").replace("+", ""))
            if num > 0:
                return color.bullish(value)
            elif num < 0:
                return color.bearish(value)
            else:
                return color.neutral(value)
        except (ValueError, TypeError):
            return value

    return re.sub(r"[+-]?\d+\.?\d*%", _replace, text)


def _print_status_list_item(
    text: str,
    *,
    color: Color,
    output: TextIO,
    bullet: str = "•",
) -> None:
    """Print a list item, colorizing the entire line based on status indicators."""
    if "✓" in text or "成功" in text:
        print(f"  {bullet} {color.success(text)}", file=output)
    elif "✗" in text or "失败" in text or "错误" in text:
        print(f"  {bullet} {color.error(text)}", file=output)
    elif "⚠" in text or "警告" in text or "注意" in text:
        print(f"  {bullet} {color.warning(text)}", file=output)
    else:
        print(f"  {bullet} {text}", file=output)


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
