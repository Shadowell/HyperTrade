"""Interactive configuration manager for HyperTrade."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

from hypertrade.ui.colors import Color, ColorTheme, get_theme
from hypertrade.ui.formatter import EnhancedFormatter


class ConfigManager:
    """Manage HyperTrade configuration with interactive UI."""

    def __init__(
        self,
        config_path: Path | None = None,
        *,
        output: TextIO | None = None,
    ):
        self.config_path = config_path or Path.home() / ".hypertrade" / "config.json"
        self.output = output or sys.stdout
        self.formatter = EnhancedFormatter(output=self.output)
        self.color = Color(output=self.output)

    def load(self) -> dict[str, Any]:
        """Load configuration from file."""
        if not self.config_path.exists():
            return self._default_config()

        try:
            with open(self.config_path) as f:
                config = json.load(f)
            return {**self._default_config(), **config}
        except Exception:
            return self._default_config()

    def save(self, config: dict[str, Any]) -> None:
        """Save configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)
        self.config_path.chmod(0o600)

    def interactive_setup(self) -> dict[str, Any]:
        """Interactive configuration setup."""
        self.formatter.banner(
            "HyperTrade Configuration",
            subtitle="Let's set up your trading environment",
        )

        config = self.load()

        # Theme selection
        self.formatter.section("Theme Settings")
        theme = self._prompt_theme()
        config["ui"]["theme"] = theme

        # Update formatter with new theme
        self.formatter = EnhancedFormatter(
            theme=get_theme(theme, output=self.output),
            output=self.output,
        )

        # Output settings
        self.formatter.section("Output Settings")
        config["ui"]["width"] = self._prompt_int(
            "Output width",
            default=config["ui"]["width"],
            min_val=60,
            max_val=200,
        )

        config["ui"]["show_progress"] = self._prompt_bool(
            "Show progress indicators",
            default=config["ui"]["show_progress"],
        )

        config["ui"]["show_timestamps"] = self._prompt_bool(
            "Show timestamps",
            default=config["ui"]["show_timestamps"],
        )

        # Agent settings
        self.formatter.section("Agent Settings")
        config["agent"]["verbose"] = self._prompt_bool(
            "Verbose output",
            default=config["agent"]["verbose"],
        )

        config["agent"]["show_tool_calls"] = self._prompt_bool(
            "Show tool call details",
            default=config["agent"]["show_tool_calls"],
        )

        # Market data settings
        self.formatter.section("Market Data Settings")
        config["market"]["auto_refresh"] = self._prompt_bool(
            "Auto-refresh market data",
            default=config["market"]["auto_refresh"],
        )

        config["market"]["refresh_interval"] = self._prompt_int(
            "Refresh interval (seconds)",
            default=config["market"]["refresh_interval"],
            min_val=10,
            max_val=3600,
        )

        # Save configuration
        self.save(config)
        self.formatter.success(f"Configuration saved to {self.config_path}")

        return config

    def show_config(self) -> None:
        """Display current configuration."""
        config = self.load()

        self.formatter.header("Current Configuration")

        # UI Settings
        self.formatter.section("UI Settings")
        self.formatter.kv("Theme", config["ui"]["theme"], indent=1)
        self.formatter.kv("Output Width", config["ui"]["width"], indent=1)
        self.formatter.kv("Progress Indicators", config["ui"]["show_progress"], indent=1)
        self.formatter.kv("Timestamps", config["ui"]["show_timestamps"], indent=1)

        # Agent Settings
        self.formatter.section("Agent Settings")
        self.formatter.kv("Verbose", config["agent"]["verbose"], indent=1)
        self.formatter.kv("Show Tool Calls", config["agent"]["show_tool_calls"], indent=1)

        # Market Settings
        self.formatter.section("Market Data Settings")
        self.formatter.kv("Auto Refresh", config["market"]["auto_refresh"], indent=1)
        self.formatter.kv(
            "Refresh Interval",
            f"{config['market']['refresh_interval']}s",
            indent=1,
        )

        print("", file=self.output)
        self.formatter.info(f"Config file: {self.config_path}")

    def _default_config(self) -> dict[str, Any]:
        """Get default configuration."""
        return {
            "ui": {
                "theme": "default",
                "width": 80,
                "show_progress": True,
                "show_timestamps": True,
            },
            "agent": {
                "verbose": False,
                "show_tool_calls": True,
            },
            "market": {
                "auto_refresh": True,
                "refresh_interval": 300,  # 5 minutes
            },
        }

    def _prompt_theme(self) -> str:
        """Prompt for theme selection."""
        themes = ["default", "dark", "light", "none"]

        print("", file=self.output)
        print("Available themes:", file=self.output)
        for i, theme in enumerate(themes, 1):
            print(f"  {i}. {theme}", file=self.output)

        while True:
            try:
                choice = input(f"Select theme (1-{len(themes)}) [1]: ").strip()
                if not choice:
                    return themes[0]

                idx = int(choice) - 1
                if 0 <= idx < len(themes):
                    return themes[idx]

                print(self.color.error(f"Invalid choice. Enter 1-{len(themes)}"), file=self.output)
            except (ValueError, KeyboardInterrupt):
                print(self.color.warning("Using default theme"), file=self.output)
                return themes[0]

    def _prompt_int(
        self,
        prompt: str,
        *,
        default: int,
        min_val: int,
        max_val: int,
    ) -> int:
        """Prompt for integer input."""
        while True:
            try:
                value = input(f"{prompt} [{default}]: ").strip()
                if not value:
                    return default

                num = int(value)
                if min_val <= num <= max_val:
                    return num

                print(
                    self.color.error(f"Value must be between {min_val} and {max_val}"),
                    file=self.output,
                )
            except ValueError:
                print(self.color.error("Invalid number"), file=self.output)
            except KeyboardInterrupt:
                print(self.color.warning(f"Using default: {default}"), file=self.output)
                return default

    def _prompt_bool(self, prompt: str, *, default: bool) -> bool:
        """Prompt for boolean input."""
        default_str = "Y/n" if default else "y/N"

        while True:
            try:
                value = input(f"{prompt} [{default_str}]: ").strip().lower()
                if not value:
                    return default

                if value in ("y", "yes", "true", "1"):
                    return True
                elif value in ("n", "no", "false", "0"):
                    return False

                print(self.color.error("Enter y/yes or n/no"), file=self.output)
            except KeyboardInterrupt:
                print(self.color.warning(f"Using default: {default}"), file=self.output)
                return default
