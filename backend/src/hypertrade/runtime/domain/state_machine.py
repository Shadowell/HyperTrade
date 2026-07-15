from hypertrade.runtime.domain.models import TERMINAL_STATUSES, MissionStatus

ALLOWED_TRANSITIONS: dict[MissionStatus, set[MissionStatus]] = {
    MissionStatus.DRAFT: {MissionStatus.PLANNING, MissionStatus.CANCELED},
    MissionStatus.PLANNING: {
        MissionStatus.RUNNING,
        MissionStatus.WAITING_INPUT,
        MissionStatus.FAILED,
        MissionStatus.CANCELED,
    },
    MissionStatus.RUNNING: {
        MissionStatus.REPLANNING,
        MissionStatus.RETRY_WAIT,
        MissionStatus.WAITING_APPROVAL,
        MissionStatus.WAITING_INPUT,
        MissionStatus.PAUSE_REQUESTED,
        MissionStatus.CANCEL_REQUESTED,
        MissionStatus.COMPLETED,
        MissionStatus.FAILED,
        MissionStatus.BUDGET_EXHAUSTED,
    },
    MissionStatus.REPLANNING: {
        MissionStatus.RUNNING,
        MissionStatus.WAITING_INPUT,
        MissionStatus.FAILED,
        MissionStatus.BUDGET_EXHAUSTED,
        MissionStatus.CANCEL_REQUESTED,
    },
    MissionStatus.RETRY_WAIT: {
        MissionStatus.RUNNING,
        MissionStatus.PAUSE_REQUESTED,
        MissionStatus.CANCEL_REQUESTED,
        MissionStatus.BUDGET_EXHAUSTED,
    },
    MissionStatus.WAITING_APPROVAL: {
        MissionStatus.RUNNING,
        MissionStatus.CANCEL_REQUESTED,
        MissionStatus.PAUSE_REQUESTED,
    },
    MissionStatus.WAITING_INPUT: {
        MissionStatus.REPLANNING,
        MissionStatus.CANCEL_REQUESTED,
    },
    MissionStatus.PAUSE_REQUESTED: {MissionStatus.PAUSED, MissionStatus.CANCEL_REQUESTED},
    MissionStatus.PAUSED: {MissionStatus.RUNNING, MissionStatus.CANCEL_REQUESTED},
    MissionStatus.CANCEL_REQUESTED: {MissionStatus.CANCELED},
}


class InvalidMissionTransition(ValueError):
    pass


def require_transition(current: MissionStatus, target: MissionStatus) -> None:
    if current in TERMINAL_STATUSES:
        raise InvalidMissionTransition(f"terminal mission cannot transition from {current}")
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidMissionTransition(f"invalid mission transition: {current} -> {target}")
