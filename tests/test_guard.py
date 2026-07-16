"""Unit tests for wpguard_mcp.guard: packet lifecycle and the guard check
that mutating tools rely on before running an apply=True write.
"""
from __future__ import annotations

import pytest

from wpguard_mcp.guard import (
    PacketAlreadyClosedError,
    PacketNotFoundError,
    PacketRequiredError,
    PacketStore,
    require_open_packet,
)


@pytest.fixture()
def store(tmp_path):
    return PacketStore(path=tmp_path / "packets.jsonl")


def test_open_packet_creates_open_packet(store):
    packet = store.open_packet(site="example.com", summary="testing widget config", risk="low")

    assert packet.site == "example.com"
    assert packet.summary == "testing widget config"
    assert packet.risk == "low"
    assert packet.is_open is True
    assert packet.closed_at is None
    assert store.get(packet.id) is packet


def test_close_packet_marks_it_closed(store):
    packet = store.open_packet(site="example.com", summary="testing", risk="low")

    closed = store.close_packet(packet.id, outcome="verified via recon")

    assert closed.is_open is False
    assert closed.closed_at is not None
    assert closed.outcome == "verified via recon"


def test_closing_already_closed_packet_raises(store):
    packet = store.open_packet(site="example.com", summary="testing", risk="low")
    store.close_packet(packet.id)

    with pytest.raises(PacketAlreadyClosedError):
        store.close_packet(packet.id)


def test_logging_to_closed_packet_raises(store):
    packet = store.open_packet(site="example.com", summary="testing", risk="low")
    store.close_packet(packet.id)

    with pytest.raises(PacketAlreadyClosedError):
        store.log(packet.id, "should not be allowed")


def test_close_unknown_packet_raises(store):
    with pytest.raises(PacketNotFoundError):
        store.close_packet("does-not-exist")


def test_log_appends_to_packet(store):
    packet = store.open_packet(site="example.com", summary="testing", risk="low")

    store.log(packet.id, "dry-run previewed option change")
    updated = store.log(packet.id, "applied option change")

    messages = [entry["message"] for entry in updated.log]
    assert messages == ["dry-run previewed option change", "applied option change"]


def test_get_open_packet_returns_none_when_no_packet_for_site(store):
    store.open_packet(site="other-site.com", summary="unrelated", risk="low")

    assert store.get_open_packet("example.com") is None


def test_get_open_packet_ignores_closed_packets(store):
    packet = store.open_packet(site="example.com", summary="testing", risk="low")
    store.close_packet(packet.id)

    assert store.get_open_packet("example.com") is None


def test_get_open_packet_returns_most_recent_open_packet(store):
    # Distinct targets so both packets can be open at once (a whole-site lock
    # would otherwise refuse the second open).
    store.open_packet(site="example.com", summary="first", risk="low", target="option:a")
    second = store.open_packet(site="example.com", summary="second", risk="medium", target="option:b")

    found = store.get_open_packet("example.com")

    assert found is not None
    assert found.id == second.id
    assert found.summary == "second"


def test_require_open_packet_blocks_when_no_packet_open(store, monkeypatch):
    monkeypatch.delenv("WPGUARD_BYPASS_GUARD", raising=False)

    with pytest.raises(PacketRequiredError):
        require_open_packet(store, "example.com")


def test_require_open_packet_blocks_proposed_but_unapproved_packet(store, monkeypatch):
    monkeypatch.delenv("WPGUARD_BYPASS_GUARD", raising=False)
    store.open_packet(site="example.com", summary="testing", risk="low")

    # An open-but-unapproved packet does NOT satisfy the guard.
    with pytest.raises(PacketRequiredError):
        require_open_packet(store, "example.com")


def test_require_open_packet_allows_when_matching_packet_approved(store):
    packet = store.open_packet(site="example.com", summary="testing", risk="low")
    store.approve_packet(packet.id, approver="tester")

    guarding_packet = require_open_packet(store, "example.com")

    assert guarding_packet.id == packet.id
    assert guarding_packet.is_open is True
    assert guarding_packet.is_approved is True


def test_require_open_packet_does_not_match_a_different_site(store, monkeypatch):
    monkeypatch.delenv("WPGUARD_BYPASS_GUARD", raising=False)
    store.open_packet(site="other-site.com", summary="unrelated change", risk="low")

    with pytest.raises(PacketRequiredError):
        require_open_packet(store, "example.com")


def test_require_open_packet_respects_bypass_env_var(store, monkeypatch):
    monkeypatch.setenv("WPGUARD_BYPASS_GUARD", "1")

    packet = require_open_packet(store, "example.com")

    assert packet.id == "bypass"
    assert packet.site == "example.com"


def test_require_open_packet_bypass_env_var_off_still_blocks(store, monkeypatch):
    monkeypatch.setenv("WPGUARD_BYPASS_GUARD", "0")

    with pytest.raises(PacketRequiredError):
        require_open_packet(store, "example.com")


def test_packet_store_persists_across_instances(tmp_path):
    path = tmp_path / "packets.jsonl"
    store_a = PacketStore(path=path)
    packet = store_a.open_packet(site="example.com", summary="persisted change", risk="high")
    store_a.log(packet.id, "note before reload")

    store_b = PacketStore(path=path)
    reloaded = store_b.get(packet.id)

    assert reloaded is not None
    assert reloaded.site == "example.com"
    assert reloaded.is_open is True
    assert reloaded.log[0]["message"] == "note before reload"


def test_list_packets_filters_by_site_and_open_only(store):
    p1 = store.open_packet(site="a.com", summary="a-open", risk="low", target="option:x")
    p2 = store.open_packet(site="a.com", summary="a-closed", risk="low", target="option:y")
    store.close_packet(p2.id)
    store.open_packet(site="b.com", summary="b-open", risk="low")

    a_packets = store.list_packets(site="a.com")
    assert {p.id for p in a_packets} == {p1.id, p2.id}

    a_open_only = store.list_packets(site="a.com", open_only=True)
    assert [p.id for p in a_open_only] == [p1.id]
