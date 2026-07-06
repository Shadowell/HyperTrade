"""Enhanced output formatter with better UX."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, TextIO

from hypertrade.ui.colors import Color, ColorTheme


class EnhancedFormatter:
    """Enhanced formatter for better terminal output."""

    def __init__(
        self,
        *,
        theme: ColorTheme | None = None,
        output: TextIO | None = None,
        width: int = 80,
    ):
        self.output = output or sys.stdout
        self.width = width
        self.color = Color(theme=theme, output=self.output)

    def header(self, title: str, *, subtitle: str = "") -> None:
        """Print a fancy header."""
        border = "═" * self.width
        print(self.color.paint(border, "border"), file=self.output)

        # Title
        padding = (self.width - len(title)) // 2
        title_line = " " * padding + title + " " * padding
        if len(title_line) < self.width:
            title_line += " " * (self.width - len(title_line))
        print(self.color.paint(title_line, "title"), file=self.output)

        # Subtitle
        if subtitle:
            padding = (self.width - len(subtitle)) // 2
            subtitle_line = " " * padding + subtitle + " " * padding
            if len(subtitle_line) < self.width:
                subtitle_line += " " * (self.width - len(subtitle_line))
            print(self.color.paint(subtitle_line, "subtitle"), file=self.output)

        print(self.color.paint(border, "border"), file=self.output)
        print("", file=self.output)

    def section(self, title: str) -> None:
        """Print a section title."""
        print("", file=self.output)
        print(self.color.paint(f"▸ {title}", "section"), file=self.output)
        print(self.color.paint("─" * self.width, "border"), file=self.output)

    def subsection(self, title: str) -> None:
        """Print a subsection title."""
        print("", file=self.output)
        print(self.color.paint(f"  ▪ {title}", "subtitle"), file=self.output)

    def kv(self, key: str, value: Any, *, indent: int = 0) -> None:
        """Print key-value pair."""
        prefix = "  " * indent
        colored_key = self.color.paint(key, "label")
        colored_value = self.color.paint(value, "value")
        print(f"{prefix}{colored_key}: {colored_value}", file=self.output)

    def list_item(self, text: str, *, indent: int = 0, bullet: str = "•") -> None:
        """Print a list item."""
        prefix = "  " * indent
        print(f"{prefix}{bullet} {text}", file=self.output)

    def success(self, message: str) -> None:
        """Print success message."""
        print(f"✓ {self.color.success(message)}", file=self.output)

    def error(self, message: str) -> None:
        """Print error message."""
        print(f"✗ {self.color.error(message)}", file=self.output)

    def warning(self, message: str) -> None:
        """Print warning message."""
        print(f"⚠ {self.color.warning(message)}", file=self.output)

    def info(self, message: str) -> None:
        """Print info message."""
        print(f"ℹ {self.color.info(message)}", file=self.output)

    def table(
        self,
        headers: list[str],
        rows: list[list[Any]],
        *,
        alignments: list[str] | None = None,
    ) -> None:
        """Print a formatted table.

        Args:
            headers: Column headers
            rows: Table rows
            alignments: Column alignments ('left', 'right', 'center')
        """
        if not rows:
            self.info("No data to display")
            return

        # Calculate column widths
        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(str(cell)))

        # Default alignments
        if alignments is None:
            alignments = ["left"] * len(headers)

        # Print header
        header_cells = []
        for i, (header, width) in enumerate(zip(headers, widths)):
            if alignments[i] == "right":
                cell = header.rjust(width)
            elif alignments[i] == "center":
                cell = header.center(width)
            else:
                cell = header.ljust(width)
            header_cells.append(self.color.paint(cell, "label"))

        print(" │ ".join(header_cells), file=self.output)
        print("─" * (sum(widths) + 3 * (len(widths) - 1)), file=self.output)

        # Print rows
        for row in rows:
            row_cells = []
            for i, (cell, width) in enumerate(zip(row, widths)):
                cell_str = str(cell)
                if alignments[i] == "right":
                    formatted = cell_str.rjust(width)
                elif alignments[i] == "center":
                    formatted = cell_str.center(width)
                else:
                    formatted = cell_str.ljust(width)
                row_cells.append(formatted)

            print(" │ ".join(row_cells), file=self.output)

    def box(self, content: str, *, title: str = "") -> None:
        """Print content in a box."""
        lines = content.split("\n")
        max_len = max(len(line) for line in lines) if lines else 0
        if title:
            max_len = max(max_len, len(title) + 4)

        box_width = min(max_len + 4, self.width - 4)

        # Top border
        if title:
            title_padded = f" {title} "
            padding = box_width - len(title_padded) - 2
            top = f"╭─{title_padded}{'─' * padding}╮"
        else:
            top = f"╭{'─' * (box_width - 2)}╮"

        print(self.color.paint(top, "border"), file=self.output)

        # Content
        for line in lines:
            padded = line.ljust(box_width - 4)
            print(
                f"{self.color.paint('│', 'border')} {padded} {self.color.paint('│', 'border')}",
                file=self.output,
            )

        # Bottom border
        bottom = f"╰{'─' * (box_width - 2)}╯"
        print(self.color.paint(bottom, "border"), file=self.output)

    def json_tree(self, data: dict[str, Any], *, indent: int = 0) -> None:
        """Print JSON data as a tree."""
        for key, value in data.items():
            prefix = "  " * indent
            if isinstance(value, dict):
                print(
                    f"{prefix}{self.color.paint(key, 'label')}: {{",
                    file=self.output,
                )
                self.json_tree(value, indent=indent + 1)
                print(f"{prefix}}}", file=self.output)
            elif isinstance(value, list):
                print(
                    f"{prefix}{self.color.paint(key, 'label')}: [",
                    file=self.output,
                )
                for item in value:
                    if isinstance(item, (dict, list)):
                        self.json_tree({"": item}, indent=indent + 1)
                    else:
                        print(
                            f"{prefix}  {self.color.paint(item, 'value')}",
                            file=self.output,
                        )
                print(f"{prefix}]", file=self.output)
            else:
                print(
                    f"{prefix}{self.color.paint(key, 'label')}: "
                    f"{self.color.paint(value, 'value')}",
                    file=self.output,
                )

    def divider(self, *, char: str = "─") -> None:
        """Print a divider line."""
        print(self.color.paint(char * self.width, "border"), file=self.output)

    def timestamp(self, dt: datetime | None = None) -> None:
        """Print current timestamp."""
        dt = dt or datetime.now()
        ts = dt.strftime("%Y-%m-%d %H:%M:%S")
        print(self.color.paint(f"🕐 {ts}", "muted"), file=self.output)

    def market_price(self, symbol: str, price: float, change: float) -> None:
        """Print market price with change."""
        price_str = self.color.price(price)
        change_str = self.color.change_percent(change)
        print(f"{self.color.bold(symbol)}: {price_str} {change_str}", file=self.output)

    def sentiment_indicator(self, value: float, *, label: str = "Sentiment") -> None:
        """Print sentiment indicator bar.

        Args:
            value: Sentiment value from -1 (bearish) to 1 (bullish)
            label: Label for the indicator
        """
        # Normalize to 0-100 scale
        normalized = int((value + 1) * 50)
        normalized = max(0, min(100, normalized))

        # Create bar
        bar_width = 40
        filled = int(bar_width * normalized / 100)

        if value > 0.5:
            fill_char = self.color.bullish("█")
        elif value < -0.5:
            fill_char = self.color.bearish("█")
        else:
            fill_char = self.color.neutral("█")

        empty_char = self.color.paint("░", "muted")

        bar = fill_char * filled + empty_char * (bar_width - filled)

        # Sentiment label
        if value > 0.5:
            sentiment = self.color.bullish("Strong Buy")
        elif value > 0:
            sentiment = self.color.bullish("Buy")
        elif value == 0:
            sentiment = self.color.neutral("Hold")
        elif value > -0.5:
            sentiment = self.color.bearish("Sell")
        else:
            sentiment = self.color.bearish("Strong Sell")

        print(
            f"{self.color.paint(label, 'label')}: [{bar}] {sentiment}",
            file=self.output,
        )

    def banner(
        self,
        title: str,
        *,
        subtitle: str = "",
        items: list[tuple[str, str]] | None = None,
    ) -> None:
        """Print an application banner.

        Args:
            title: Main title
            subtitle: Subtitle text
            items: List of (label, value) tuples to display
        """
        border = "═" * self.width

        print(self.color.paint(f"╔{border}╗", "border"), file=self.output)

        # Title
        padding = (self.width - len(title)) // 2
        title_line = " " * padding + title + " " * padding
        if len(title_line) < self.width:
            title_line += " " * (self.width - len(title_line))
        print(
            f"{self.color.paint('║', 'border')}{self.color.paint(title_line, 'title')}"
            f"{self.color.paint('║', 'border')}",
            file=self.output,
        )

        # Subtitle
        if subtitle:
            padding = (self.width - len(subtitle)) // 2
            subtitle_line = " " * padding + subtitle + " " * padding
            if len(subtitle_line) < self.width:
                subtitle_line += " " * (self.width - len(subtitle_line))
            print(
                f"{self.color.paint('║', 'border')}{self.color.paint(subtitle_line, 'subtitle')}"
                f"{self.color.paint('║', 'border')}",
                file=self.output,
            )

        print(self.color.paint(f"╚{border}╝", "border"), file=self.output)

        # Items
        if items:
            print("", file=self.output)
            for label, value in items:
                self.kv(label, value)

        print("", file=self.output)
