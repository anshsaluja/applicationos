"""Checkpoint identity safety regressions independent of PostgreSQL availability."""

from uuid import uuid4

import pytest

from app.durable_planning import checkpoint_config


@pytest.mark.parametrize(
    "identifier",
    [" leading", "trailing ", "\tbad", "bad\nkey", "bad\x00key", "bad\x7fkey", "x" * 129, "bad\u200bkey", "bad\u2060key", "bad\u00a0key", "bad\ud800key", "bad\u0378key"],
)
def test_ambiguous_checkpoint_keys_are_rejected(identifier: str) -> None:
    with pytest.raises(ValueError, match="thread_id"):
        checkpoint_config(identifier)


def test_uuid_checkpoint_identity_is_stable_across_restarts() -> None:
    action_id = uuid4()
    expected = {"configurable": {"thread_id": str(action_id)}}
    assert checkpoint_config(action_id) == expected
    assert checkpoint_config(str(action_id)) == expected


def test_distinct_checkpoint_keys_remain_distinct() -> None:
    assert checkpoint_config("workflow-a") != checkpoint_config("workflow-b")


@pytest.mark.parametrize("identifier", ["cafe\u0301", "A\u030a", "\u212b"])
def test_noncanonical_unicode_checkpoint_identity_is_rejected(identifier: str) -> None:
    """Visually equivalent keys must not silently create separate histories."""
    with pytest.raises(ValueError, match="thread_id"):
        checkpoint_config(identifier)


def test_canonical_unicode_checkpoint_identity_is_preserved() -> None:
    assert checkpoint_config("caf\u00e9") == {"configurable": {"thread_id": "caf\u00e9"}}
