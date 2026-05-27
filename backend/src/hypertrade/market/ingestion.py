from dataclasses import dataclass


@dataclass
class IngestionHealth:
    max_failures_before_fallback: int = 3
    ws_failures: int = 0

    @property
    def should_use_rest_fallback(self) -> bool:
        return self.ws_failures >= self.max_failures_before_fallback

    def record_ws_failure(self) -> None:
        self.ws_failures += 1

    def record_ws_success(self) -> None:
        self.ws_failures = 0
