"""Shared control interruption used at research graph dispatch safe points."""


class ResearchGraphControlInterrupted(RuntimeError):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(f"research graph interrupted: {status}: {reason}")
        self.status = status
        self.reason = reason
