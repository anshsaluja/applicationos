"""Regression coverage for transactional session cleanup on all exit paths."""

from unittest.mock import Mock

import pytest

from app.persistence import session_scope


def test_session_scope_commits_once_and_closes_on_success():
    session = Mock()
    factory = Mock(return_value=session)

    with session_scope(factory) as active:
        assert active is session

    factory.assert_called_once_with()
    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()
    session.close.assert_called_once_with()


def test_session_scope_rolls_back_and_closes_on_body_failure():
    session = Mock()
    failure = RuntimeError("reject incomplete workflow")

    with pytest.raises(RuntimeError, match="reject incomplete workflow") as caught, session_scope(lambda: session):
        raise failure

    assert caught.value is failure
    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


def test_session_scope_rolls_back_and_closes_on_commit_failure():
    session = Mock()
    failure = RuntimeError("database commit failed")
    session.commit.side_effect = failure

    with pytest.raises(RuntimeError, match="database commit failed") as caught, session_scope(lambda: session):
        pass

    assert caught.value is failure
    session.commit.assert_called_once_with()
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_session_scope_rolls_back_and_closes_on_interruption(interruption):
    session = Mock()
    failure = interruption("interrupted before commit")

    with pytest.raises(interruption) as caught, session_scope(lambda: session):
        raise failure

    assert caught.value is failure
    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


def test_session_scope_does_not_commit_when_rollback_fails():
    """Preserve the original workflow error even when database rollback fails."""
    session = Mock()
    session.rollback.side_effect = RuntimeError("database connection lost during rollback")
    failure = ValueError("workflow rejected")

    with pytest.raises(ValueError, match="workflow rejected") as caught, session_scope(lambda: session):
        raise failure

    assert caught.value is failure
    assert any("Rollback also failed" in note for note in caught.value.__notes__)
    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
