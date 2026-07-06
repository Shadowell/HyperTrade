"""Progress indicators for terminal UI."""

from __future__ import annotations

import sys
import threading
import time
from typing import TextIO


class ProgressBar:
    """Terminal progress bar with percentage and ETA."""

    def __init__(
        self,
        total: int,
        *,
        width: int = 50,
        prefix: str = "",
        suffix: str = "",
        fill: str = "█",
        empty: str = "░",
        output: TextIO | None = None,
    ):
        self.total = total
        self.current = 0
        self.width = width
        self.prefix = prefix
        self.suffix = suffix
        self.fill = fill
        self.empty = empty
        self.output = output or sys.stdout
        self.start_time = time.time()

    def update(self, current: int | None = None) -> None:
        """Update progress bar.

        Args:
            current: Current progress (if None, increment by 1)
        """
        if current is not None:
            self.current = current
        else:
            self.current += 1

        self._render()

    def finish(self) -> None:
        """Finish progress bar and move to next line."""
        self.current = self.total
        self._render()
        print("", file=self.output)

    def _render(self) -> None:
        """Render progress bar to output."""
        percent = (self.current / self.total) * 100 if self.total > 0 else 0
        filled = int(self.width * self.current / self.total) if self.total > 0 else 0
        bar = self.fill * filled + self.empty * (self.width - filled)

        # Calculate ETA
        elapsed = time.time() - self.start_time
        if self.current > 0:
            eta = (elapsed / self.current) * (self.total - self.current)
            eta_str = f" ETA: {eta:.0f}s"
        else:
            eta_str = ""

        # Build output
        output = f"\r{self.prefix}{bar} {percent:.1f}%{eta_str}{self.suffix}"
        print(output, end="", file=self.output, flush=True)


class Spinner:
    """Terminal spinner for indeterminate progress."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    DOTS = ["⠁", "⠂", "⠄", "⡀", "⢀", "⠠", "⠐", "⠈"]
    ARROW = ["←", "↖", "↑", "↗", "→", "↘", "↓", "↙"]
    LINE = ["|", "/", "-", "\\"]
    CIRCLE = ["◐", "◓", "◑", "◒"]
    GROWING = ["▁", "▃", "▄", "▅", "▆", "▇", "█", "▇", "▆", "▅", "▄", "▃"]

    def __init__(
        self,
        message: str = "Processing",
        *,
        frames: list[str] | None = None,
        interval: float = 0.1,
        output: TextIO | None = None,
    ):
        self.message = message
        self.frames = frames or self.FRAMES
        self.interval = interval
        self.output = output or sys.stdout
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_index = 0

    def start(self) -> Spinner:
        """Start spinning."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def stop(self, final_message: str | None = None) -> None:
        """Stop spinning and optionally show final message."""
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        # Clear spinner line
        print(f"\r{' ' * (len(self.message) + 10)}\r", end="", file=self.output, flush=True)
        if final_message:
            print(final_message, file=self.output)

    def update_message(self, message: str) -> None:
        """Update spinner message."""
        self.message = message

    def _spin(self) -> None:
        """Spin animation loop."""
        while not self._stop_event.is_set():
            frame = self.frames[self._frame_index % len(self.frames)]
            print(
                f"\r{frame} {self.message}...",
                end="",
                file=self.output,
                flush=True,
            )
            self._frame_index += 1
            time.sleep(self.interval)

    def __enter__(self) -> Spinner:
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit."""
        self.stop()


class MultiSpinner:
    """Multiple spinners for concurrent tasks."""

    def __init__(self, *, output: TextIO | None = None):
        self.output = output or sys.stdout
        self.spinners: dict[str, tuple[str, int]] = {}  # task_id -> (message, frame_index)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._frames = Spinner.FRAMES

    def add(self, task_id: str, message: str) -> None:
        """Add a new task to track."""
        self.spinners[task_id] = (message, 0)

    def update(self, task_id: str, message: str) -> None:
        """Update task message."""
        if task_id in self.spinners:
            _, frame_idx = self.spinners[task_id]
            self.spinners[task_id] = (message, frame_idx)

    def complete(self, task_id: str, message: str = "✓ Done") -> None:
        """Mark task as complete."""
        if task_id in self.spinners:
            del self.spinners[task_id]
        # Print completion message
        print(f"{message}", file=self.output)

    def start(self) -> MultiSpinner:
        """Start all spinners."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin_all, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop all spinners."""
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        # Clear lines
        for _ in self.spinners:
            print("\r" + " " * 80, file=self.output)
        print("\r", end="", file=self.output, flush=True)

    def _spin_all(self) -> None:
        """Spin animation loop for all tasks."""
        while not self._stop_event.is_set():
            # Save cursor position
            print("\033[s", end="", file=self.output, flush=True)

            for idx, (task_id, (message, frame_idx)) in enumerate(self.spinners.items()):
                frame = self._frames[frame_idx % len(self._frames)]
                # Move cursor and print
                if idx > 0:
                    print("\n", end="", file=self.output)
                print(f"\r{frame} {message}...", end="", file=self.output, flush=True)
                # Update frame index
                self.spinners[task_id] = (message, frame_idx + 1)

            # Restore cursor position
            print("\033[u", end="", file=self.output, flush=True)
            time.sleep(0.1)

    def __enter__(self) -> MultiSpinner:
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit."""
        self.stop()
