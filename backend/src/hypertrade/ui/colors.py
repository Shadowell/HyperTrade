"""Terminal color management with theme support."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TextIO


@dataclass(frozen=True)
class ColorTheme:
    """Terminal color theme with semantic color assignments."""

    # Basic colors
    reset: str
    bold: str
    dim: str
    italic: str
    underline: str

    # UI elements
    border: str
    title: str
    subtitle: str
    section: str

    # Content types
    command: str
    tool: str
    category: str
    label: str
    value: str
    muted: str

    # Status colors
    info: str
    success: str
    warning: str
    error: str

    # Trading-specific
    bullish: str
    bearish: str
    neutral: str

    # Market sentiment
    strong_buy: str
    buy: str
    hold: str
    sell: str
    strong_sell: str

    @classmethod
    def default(cls, *, output: TextIO | None = None) -> ColorTheme:
        """Create default color theme (256-color support)."""
        output = output or sys.stdout
        if not _supports_color(output):
            return cls.no_color()

        return cls(
            # Basic
            reset="\033[0m",
            bold="\033[1m",
            dim="\033[2m",
            italic="\033[3m",
            underline="\033[4m",

            # UI elements
            border="\033[38;5;81m",        # Bright cyan
            title="\033[1;38;5;45m",       # Bold bright cyan
            subtitle="\033[38;5;117m",     # Light blue
            section="\033[1;38;5;183m",    # Bold lavender

            # Content types
            command="\033[38;5;121m",      # Light green
            tool="\033[38;5;111m",         # Steel blue
            category="\033[38;5;110m",     # Blue
            label="\033[38;5;110m",        # Blue
            value="\033[1;38;5;159m",      # Bold cyan
            muted="\033[38;5;246m",        # Gray

            # Status
            info="\033[38;5;117m",         # Light blue
            success="\033[38;5;120m",      # Light green
            warning="\033[38;5;214m",      # Orange
            error="\033[38;5;203m",        # Red

            # Trading
            bullish="\033[38;5;82m",       # Bright green
            bearish="\033[38;5;196m",      # Bright red
            neutral="\033[38;5;226m",      # Yellow

            # Market sentiment
            strong_buy="\033[1;38;5;46m",  # Bold bright green
            buy="\033[38;5;82m",           # Green
            hold="\033[38;5;226m",         # Yellow
            sell="\033[38;5;208m",         # Orange
            strong_sell="\033[1;38;5;196m",# Bold red
        )

    @classmethod
    def dark(cls) -> ColorTheme:
        """Dark theme optimized for dark terminals."""
        return cls(
            # Basic
            reset="\033[0m",
            bold="\033[1m",
            dim="\033[2m",
            italic="\033[3m",
            underline="\033[4m",

            # UI elements (brighter for dark bg)
            border="\033[38;5;87m",
            title="\033[1;38;5;51m",
            subtitle="\033[38;5;123m",
            section="\033[1;38;5;189m",

            # Content
            command="\033[38;5;156m",
            tool="\033[38;5;117m",
            category="\033[38;5;116m",
            label="\033[38;5;116m",
            value="\033[1;38;5;195m",
            muted="\033[38;5;250m",

            # Status
            info="\033[38;5;123m",
            success="\033[38;5;156m",
            warning="\033[38;5;220m",
            error="\033[38;5;209m",

            # Trading
            bullish="\033[38;5;120m",
            bearish="\033[38;5;203m",
            neutral="\033[38;5;228m",

            # Market sentiment
            strong_buy="\033[1;38;5;82m",
            buy="\033[38;5;120m",
            hold="\033[38;5;228m",
            sell="\033[38;5;214m",
            strong_sell="\033[1;38;5;203m",
        )

    @classmethod
    def light(cls) -> ColorTheme:
        """Light theme optimized for light terminals."""
        return cls(
            # Basic
            reset="\033[0m",
            bold="\033[1m",
            dim="\033[2m",
            italic="\033[3m",
            underline="\033[4m",

            # UI elements (darker for light bg)
            border="\033[38;5;33m",
            title="\033[1;38;5;27m",
            subtitle="\033[38;5;69m",
            section="\033[1;38;5;99m",

            # Content
            command="\033[38;5;28m",
            tool="\033[38;5;61m",
            category="\033[38;5;62m",
            label="\033[38;5;62m",
            value="\033[1;38;5;33m",
            muted="\033[38;5;240m",

            # Status
            info="\033[38;5;69m",
            success="\033[38;5;28m",
            warning="\033[38;5;166m",
            error="\033[38;5;160m",

            # Trading
            bullish="\033[38;5;34m",
            bearish="\033[38;5;160m",
            neutral="\033[38;5;178m",

            # Market sentiment
            strong_buy="\033[1;38;5;28m",
            buy="\033[38;5;34m",
            hold="\033[38;5;178m",
            sell="\033[38;5;166m",
            strong_sell="\033[1;38;5;160m",
        )

    @classmethod
    def no_color(cls) -> ColorTheme:
        """No-color theme for non-TTY or NO_COLOR environment."""
        empty = ""
        return cls(
            reset=empty, bold=empty, dim=empty, italic=empty, underline=empty,
            border=empty, title=empty, subtitle=empty, section=empty,
            command=empty, tool=empty, category=empty, label=empty,
            value=empty, muted=empty, info=empty, success=empty,
            warning=empty, error=empty, bullish=empty, bearish=empty,
            neutral=empty, strong_buy=empty, buy=empty, hold=empty,
            sell=empty, strong_sell=empty,
        )


class Color:
    """Color utility for terminal output."""

    def __init__(self, theme: ColorTheme | None = None, *, output: TextIO | None = None):
        self.theme = theme or ColorTheme.default(output=output)
        self._output = output or sys.stdout

    def paint(self, text: object, style: str) -> str:
        """Paint text with a semantic color style."""
        value = str(text)
        color_code = getattr(self.theme, style, "")
        if not color_code:
            return value
        return f"{color_code}{value}{self.theme.reset}"

    def bold(self, text: object) -> str:
        """Make text bold."""
        return f"{self.theme.bold}{text}{self.theme.reset}"

    def dim(self, text: object) -> str:
        """Make text dimmed."""
        return f"{self.theme.dim}{text}{self.theme.reset}"

    def italic(self, text: object) -> str:
        """Make text italic."""
        return f"{self.theme.italic}{text}{self.theme.reset}"

    def underline(self, text: object) -> str:
        """Make text underlined."""
        return f"{self.theme.underline}{text}{self.theme.reset}"

    def success(self, text: object) -> str:
        """Paint text as success (green)."""
        return self.paint(text, "success")

    def error(self, text: object) -> str:
        """Paint text as error (red)."""
        return self.paint(text, "error")

    def warning(self, text: object) -> str:
        """Paint text as warning (orange)."""
        return self.paint(text, "warning")

    def info(self, text: object) -> str:
        """Paint text as info (blue)."""
        return self.paint(text, "info")

    def bullish(self, text: object) -> str:
        """Paint text as bullish (green)."""
        return self.paint(text, "bullish")

    def bearish(self, text: object) -> str:
        """Paint text as bearish (red)."""
        return self.paint(text, "bearish")

    def neutral(self, text: object) -> str:
        """Paint text as neutral (yellow)."""
        return self.paint(text, "neutral")

    def sentiment(self, value: float | str, *, threshold: float = 0.5) -> str:
        """Paint value based on sentiment (-1 to 1 scale).

        Args:
            value: Numeric value or string to color
            threshold: Threshold for strong buy/sell (default 0.5)

        Returns:
            Colored string based on sentiment
        """
        try:
            num = float(value)
        except (ValueError, TypeError):
            return str(value)

        if num >= threshold:
            style = "strong_buy"
        elif num > 0:
            style = "buy"
        elif num == 0:
            style = "hold"
        elif num > -threshold:
            style = "sell"
        else:
            style = "strong_sell"

        return self.paint(value, style)

    def change_percent(self, value: float | str) -> str:
        """Paint percentage change with color.

        Args:
            value: Percentage value (can include % symbol)

        Returns:
            Colored string with +/- prefix
        """
        try:
            # Remove % symbol if present
            clean = str(value).replace("%", "").strip()
            num = float(clean)
        except (ValueError, TypeError):
            return str(value)

        if num > 0:
            return self.bullish(f"+{num:.2f}%")
        elif num < 0:
            return self.bearish(f"{num:.2f}%")
        else:
            return self.neutral(f"{num:.2f}%")

    def price(self, value: float | str, *, prefix: str = "$") -> str:
        """Format and color price value.

        Args:
            value: Price value
            prefix: Currency prefix (default $)

        Returns:
            Formatted price string
        """
        try:
            num = float(value)
            formatted = f"{prefix}{num:,.2f}"
            return self.paint(formatted, "value")
        except (ValueError, TypeError):
            return str(value)


def _supports_color(output: TextIO) -> bool:
    """Check if output stream supports color."""
    # Respect NO_COLOR environment variable
    if os.getenv("NO_COLOR"):
        return False

    # Check if output is a TTY
    if not hasattr(output, "isatty") or not output.isatty():
        return False

    # Check TERM environment variable
    term = os.getenv("TERM", "")
    return term != "dumb"


def get_theme(name: str = "default", *, output: TextIO | None = None) -> ColorTheme:
    """Get color theme by name.

    Args:
        name: Theme name (default, dark, light, none)
        output: Output stream for auto-detection

    Returns:
        ColorTheme instance
    """
    name = name.lower()

    if name == "dark":
        return ColorTheme.dark()
    elif name == "light":
        return ColorTheme.light()
    elif name == "none":
        return ColorTheme.no_color()
    else:
        return ColorTheme.default(output=output)
