"""Issue #11: read-only audit view over the ledgers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from wpguard_mcp import audit
from wpguard_mcp.guard import PacketStore, SnapshotStore


@pytest.fixture()
def stores(tmp_path):
    return PacketStore(path=tmp_path / "packets.jsonl"), SnapshotStore(path=tmp_path / "snapshots.jsonl")


def test_parse_since():
    assert audit.parse_since("7d") == timedelta(days=7)
    assert audit.parse_since("24h") == timedelta(hours=24)
    assert audit.parse_since("30m") == timedelta(minutes=30)
    assert audit.parse_since("90s") == timedelta(seconds=90)


def test_parse_since_invalid():
    with pytest.raises(audit.InvalidSinceError):
        audit.parse_since("banana")


def test_build_report_includes_snapshots(stores):
    ps, ss = stores
    packet = ps.open_packet(site="a.com", summary="rename", target="option:x")
    ps.approve_packet(packet.id, approver="alice")
    ss.record(
        packet_id=packet.id, site="a.com", tool="wp_mutate_option", target="x",
        previous_value="old", new_value="new", reread=["option", "x"],
    )

    report = audit.build_report(ps, ss)
    assert len(report) == 1
    assert report[0]["id"] == packet.id
    assert report[0]["approver"] == "alice"
    assert report[0]["snapshots"][0]["previous_value"] == "old"
    assert report[0]["snapshots"][0]["new_value"] == "new"


def test_build_report_filters_by_site_and_status(stores):
    ps, ss = stores
    ps.open_packet(site="a.com", summary="a", target="option:x")
    b = ps.open_packet(site="b.com", summary="b", target="option:y")
    ps.approve_packet(b.id, approver="bob")

    assert [r["site"] for r in audit.build_report(ps, ss, site="b.com")] == ["b.com"]
    assert [r["status"] for r in audit.build_report(ps, ss, status="approved")] == ["approved"]


def test_build_report_since_window(stores):
    ps, ss = stores
    now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    old = ps.open_packet(site="a.com", summary="old", target="option:x")
    # Rewrite opened_at to 10 days ago by re-applying an open event in-memory.
    ps._packets[old.id].opened_at = (now - timedelta(days=10)).isoformat()
    ps.open_packet(site="a.com", summary="recent", target="option:y")

    report = audit.build_report(ps, ss, since=timedelta(days=7), now=now)
    summaries = [r["summary"] for r in report]
    assert "recent" in summaries
    assert "old" not in summaries


def test_render_text_smoke(stores):
    ps, ss = stores
    packet = ps.open_packet(site="a.com", summary="rename", target="option:x")
    ps.approve_packet(packet.id, approver="alice")
    ps.close_packet(packet.id, outcome="verified")
    text = audit.render_text(audit.build_report(ps, ss))
    assert "CLOSED" in text
    assert "rename" in text
    assert "verified" in text


def test_render_text_empty():
    assert "No packets" in audit.render_text([])


def test_cli_main_runs(stores, monkeypatch, capsys):
    ps, ss = stores
    ps.open_packet(site="a.com", summary="hello", target="option:x")
    monkeypatch.setattr(audit, "get_packet_store", lambda: ps)
    monkeypatch.setattr(audit, "get_snapshot_store", lambda: ss)

    rc = audit.main(["audit", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "hello" in out
