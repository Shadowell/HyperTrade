"""Deterministic concurrency boundaries for SQLite's single in-memory connection."""

from __future__ import annotations

from threading import Event, Thread

import pytest
from hypertrade.db import Database
from sqlalchemy import text


def test_in_memory_sessions_do_not_overlap_on_one_database_instance() -> None:
    db = Database("sqlite:///:memory:")
    first_entered, release_first = Event(), Event()
    second_started, second_entered = Event(), Event()
    errors: list[BaseException] = []

    def holder() -> None:
        try:
            with db.session() as session:
                session.execute(text("SELECT 1"))
                first_entered.set()
                assert release_first.wait(3)
        except BaseException as exc:
            errors.append(exc)

    def contender() -> None:
        try:
            second_started.set()
            with db.session():
                second_entered.set()
        except BaseException as exc:
            errors.append(exc)

    first = Thread(target=holder, daemon=True)
    second = Thread(target=contender, daemon=True)
    first.start()
    try:
        assert first_entered.wait(3)
        second.start()
        assert second_started.wait(3)
        assert not second_entered.wait(0.15)
    finally:
        release_first.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert second_entered.is_set()
    assert errors == []


def test_in_memory_session_exception_releases_waiting_thread() -> None:
    db = Database("sqlite:///:memory:")
    first_entered, release_first = Event(), Event()
    second_started, second_entered = Event(), Event()
    errors: list[BaseException] = []

    def failing_holder() -> None:
        try:
            with db.session() as session:
                session.execute(text("SELECT 1"))
                first_entered.set()
                assert release_first.wait(3)
                raise RuntimeError("abort transaction")
        except BaseException as exc:
            errors.append(exc)

    def contender() -> None:
        try:
            second_started.set()
            with db.session() as session:
                assert session.execute(text("SELECT 1")).scalar_one() == 1
                second_entered.set()
        except BaseException as exc:
            errors.append(exc)

    first = Thread(target=failing_holder, daemon=True)
    second = Thread(target=contender, daemon=True)
    first.start()
    try:
        assert first_entered.wait(3)
        second.start()
        assert second_started.wait(3)
        assert not second_entered.wait(0.15)
    finally:
        release_first.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert second_entered.is_set()
    assert len(errors) == 1 and str(errors[0]) == "abort transaction"


@pytest.mark.parametrize("phase", ["commit", "rollback", "close"])
def test_memory_lock_covers_transaction_finalization(phase: str) -> None:
    db = Database("sqlite:///:memory:")
    original_factory = db.session_factory
    created = 0
    finalizing, release, contender_started, contender_entered = (
        Event(), Event(), Event(), Event()
    )
    errors: list[BaseException] = []

    def instrumented_factory():
        nonlocal created
        session = original_factory()
        created += 1
        if created == 1:
            original_method = getattr(session, phase)

            def blocked_finalization():
                finalizing.set()
                assert release.wait(3)
                return original_method()

            setattr(session, phase, blocked_finalization)
        return session

    db.session_factory = instrumented_factory

    def holder() -> None:
        try:
            with db.session() as session:
                session.execute(text("SELECT 1"))
                if phase == "rollback":
                    raise RuntimeError("expected rollback")
        except RuntimeError as exc:
            if str(exc) != "expected rollback":
                errors.append(exc)
        except BaseException as exc:
            errors.append(exc)

    def contender() -> None:
        try:
            contender_started.set()
            with db.session():
                contender_entered.set()
        except BaseException as exc:
            errors.append(exc)

    first = Thread(target=holder, daemon=True)
    second = Thread(target=contender, daemon=True)
    first.start()
    try:
        assert finalizing.wait(3)
        second.start()
        assert contender_started.wait(3)
        assert not contender_entered.wait(0.15)
    finally:
        release.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert contender_entered.is_set()
    assert errors == []


def _assert_sessions_can_overlap(first_db: Database, second_db: Database) -> None:
    held, release, other_entered = Event(), Event(), Event()

    def holder() -> None:
        with first_db.session():
            held.set()
            assert release.wait(3)

    def independent() -> None:
        with second_db.session():
            other_entered.set()

    first = Thread(target=holder, daemon=True)
    second = Thread(target=independent, daemon=True)
    first.start()
    try:
        assert held.wait(3)
        second.start()
        assert other_entered.wait(3)
    finally:
        release.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not first.is_alive() and not second.is_alive()


def test_separate_memory_instances_and_file_sqlite_sessions_do_not_share_lock(tmp_path) -> None:
    _assert_sessions_can_overlap(Database("sqlite:///:memory:"), Database("sqlite:///:memory:"))
    file_db = Database(f"sqlite:///{tmp_path / 'file.db'}")
    _assert_sessions_can_overlap(file_db, file_db)
