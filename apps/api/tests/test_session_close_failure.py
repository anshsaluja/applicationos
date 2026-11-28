"""Regression tests for transaction cleanup failures and exception precedence."""

import pytest

from app.persistence import session_scope


class FakeSession:
    def __init__(self, *, commit_error=None, rollback_error=None, close_error=None):
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.close_error = close_error
        self.calls = []

    def commit(self):
        self.calls.append("commit")
        if self.commit_error:
            raise self.commit_error

    def rollback(self):
        self.calls.append("rollback")
        if self.rollback_error:
            raise self.rollback_error

    def close(self):
        self.calls.append("close")
        if self.close_error:
            raise self.close_error


def test_workflow_failure_survives_failed_close():
    session = FakeSession(close_error=OSError("close failed"))
    original = ValueError("workflow failed")
    with pytest.raises(ValueError) as caught, session_scope(lambda: session):
        raise original
    assert caught.value is original
    assert session.calls == ["rollback", "close"]
    assert any("Session close also failed: OSError" in note for note in original.__notes__)


def test_commit_failure_survives_rollback_and_close_failures():
    original = RuntimeError("commit failed")
    session = FakeSession(
        commit_error=original,
        rollback_error=OSError("rollback failed"),
        close_error=OSError("close failed"),
    )
    with pytest.raises(RuntimeError) as caught, session_scope(lambda: session):
        pass
    assert caught.value is original
    assert session.calls == ["commit", "rollback", "close"]
    assert any("Rollback also failed: OSError" in note for note in original.__notes__)
    assert any("Session close also failed: OSError" in note for note in original.__notes__)


def test_close_failure_after_success_is_not_suppressed():
    session = FakeSession(close_error=OSError("close failed"))
    with pytest.raises(OSError, match="close failed"), session_scope(lambda: session):
        pass
    assert session.calls == ["commit", "close"]


@pytest.mark.parametrize("cleanup_error", [KeyboardInterrupt("rollback interrupted"), SystemExit("rollback exited")])
def test_primary_failure_survives_cleanup_interruption(cleanup_error):
    original = ValueError("workflow failed")
    session = FakeSession(rollback_error=cleanup_error, close_error=cleanup_error)
    with pytest.raises(ValueError) as caught, session_scope(lambda: session):
        raise original
    assert caught.value is original
    assert session.calls == ["rollback", "close"]
    assert any("Rollback also failed:" in note for note in original.__notes__)
    assert any("Session close also failed:" in note for note in original.__notes__)


@pytest.mark.parametrize("cleanup_error", [KeyboardInterrupt("close interrupted"), SystemExit("close exited")])
def test_successful_commit_surfaces_close_interruption(cleanup_error):
    session = FakeSession(close_error=cleanup_error)
    with pytest.raises(type(cleanup_error)) as caught, session_scope(lambda: session):
        pass
    assert caught.value is cleanup_error
    assert session.calls == ["commit", "close"]
