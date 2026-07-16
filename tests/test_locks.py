"""Issue #3: per-target locking + status filtering on the packet store."""
from __future__ import annotations

import pytest

from wpguard_mcp.guard import (
    STATUS_APPROVED,
    STATUS_PROPOSED,
    PacketStore,
    TargetLockedError,
)


@pytest.fixture()
def store(tmp_path):
    return PacketStore(path=tmp_path / "packets.jsonl")


def test_whole_site_lock_blocks_second_open(store):
    store.open_packet(site="a.com", summary="first")
    with pytest.raises(TargetLockedError):
        store.open_packet(site="a.com", summary="second")


def test_distinct_targets_can_be_open_together(store):
    p1 = store.open_packet(site="a.com", summary="opt", target="option:x")
    p2 = store.open_packet(site="a.com", summary="meta", target="post:1:k")
    assert p1.id != p2.id


def test_same_target_conflicts(store):
    store.open_packet(site="a.com", summary="opt", target="option:x")
    with pytest.raises(TargetLockedError):
        store.open_packet(site="a.com", summary="opt again", target="option:x")


def test_wildcard_conflicts_with_specific_target(store):
    store.open_packet(site="a.com", summary="opt", target="option:x")
    with pytest.raises(TargetLockedError):
        store.open_packet(site="a.com", summary="whole site", target="*")


def test_lock_released_after_close(store):
    p1 = store.open_packet(site="a.com", summary="first", target="option:x")
    store.close_packet(p1.id)
    # Same target is free again.
    p2 = store.open_packet(site="a.com", summary="second", target="option:x")
    assert p2.id != p1.id


def test_expired_lock_does_not_block(store, monkeypatch):
    monkeypatch.setenv("WPGUARD_LOCK_TTL_SECONDS", "0")
    store.open_packet(site="a.com", summary="first", target="option:x")
    # TTL of 0 means the lock is already expired, so a new open succeeds.
    p2 = store.open_packet(site="a.com", summary="second", target="option:x")
    assert p2 is not None


def test_list_packets_filters_by_status(store):
    p1 = store.open_packet(site="a.com", summary="proposed", target="option:x")
    p2 = store.open_packet(site="a.com", summary="approved", target="option:y")
    store.approve_packet(p2.id, approver="bob")

    proposed = store.list_packets(status=STATUS_PROPOSED)
    approved = store.list_packets(status=STATUS_APPROVED)

    assert [p.id for p in proposed] == [p1.id]
    assert [p.id for p in approved] == [p2.id]
