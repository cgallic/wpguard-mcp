from __future__ import annotations

from types import SimpleNamespace

import pytest

from wpguard_mcp import corrections
from wpguard_mcp.config import SiteConfig
from wpguard_mcp.corrections import CorrectionStore
from wpguard_mcp.guard import ConflictError, PacketStore, SnapshotStore
from wpguard_mcp.tools import revisions


@pytest.fixture()
def revision_flow(monkeypatch, tmp_path):
    site = SiteConfig(name="example", transport="companion_plugin",
                      plugin_url="https://example.test/wp-json/wpguard/v1/exec",
                      plugin_api_key_env="TEST_KEY")
    packets = PacketStore(tmp_path / "packets.jsonl")
    snapshots = SnapshotStore(tmp_path / "snapshots.jsonl")
    monkeypatch.setattr(revisions, "get_site_registry", lambda: SimpleNamespace(get=lambda _name: site))
    monkeypatch.setattr(revisions, "get_packet_store", lambda: packets)
    monkeypatch.setattr(revisions, "get_snapshot_store", lambda: snapshots)
    monkeypatch.setattr(corrections, "get_correction_store", lambda: CorrectionStore(tmp_path / "c.jsonl"))
    state = {"content": "Current", "writes": []}

    def call(_site, command, args=None):
        args = args or {}
        if command == "post_content_get":
            return {"id": 7, "post_type": "page", "title": "Target", "slug": "target",
                    "status": "publish", "modified": "now", "content": state["content"]}
        if command == "revision_list":
            return {"revisions": [{"revision_id": 90}]}
        if command == "revision_get":
            return {"revision_id": args["revision_id"], "parent_id": 7, "date": "yesterday",
                    "modified": "yesterday", "author": 1, "content": "Previous"}
        if command == "revision_revert":
            state["writes"].append(args)
            state["content"] = "Previous"
            return {"restored": True}
        if command == "revision_find":
            return {"revision_id": 102}
        raise AssertionError(command)

    monkeypatch.setattr(revisions.companion_plugin, "call", call)
    monkeypatch.setattr(revisions, "_verified_revision",
                        lambda _site, _post, sha, exclude_revision_ids=None: {
                            "supported": True, "revision_id": 102,
                            "content_sha256": sha, "verified": True,
                        })
    return state, packets, snapshots


def test_revision_list_and_get_verify_parent_and_hash_content(revision_flow):
    listed = revisions.wp_revision_list("example", 7)
    assert listed["revisions"][0]["revision_id"] == 90
    assert len(listed["revisions"][0]["content_sha256"]) == 64
    got = revisions.wp_revision_get("example", 7, 90)["revision"]
    assert got["content"]["untrusted_content"] == "Previous"


def test_revision_get_rejects_wrong_parent(revision_flow, monkeypatch):
    original = revisions.companion_plugin.call

    def wrong_parent(site, command, args=None):
        result = original(site, command, args)
        if command == "revision_get":
            result["parent_id"] = 8
        return result

    monkeypatch.setattr(revisions.companion_plugin, "call", wrong_parent)
    with pytest.raises(ValueError, match="does not belong"):
        revisions.wp_revision_get("example", 7, 90)


def test_revert_preview_apply_is_guarded_snapshotted_and_revision_verified(revision_flow):
    state, packets, snapshots = revision_flow
    preview = revisions.wp_revert_to_revision("example", 7, 90)
    packet = packets.open_packet("example", "Restore revision", target="post:7:content",
                                 verb="wp_revert_to_revision", change_digest=preview["change_digest"])
    packets.approve_packet(packet.id, "owner")
    result = revisions.wp_revert_to_revision("example", 7, 90, apply=True, expected_etag=preview["etag"])
    assert result["applied"] is True
    assert result["fields_restored"] == ["post_content"]
    assert result["resulting_revision"]["revision_id"] == 102
    assert state["content"] == "Previous"
    assert len(snapshots.list_for_packet(packet.id)) == 1


def test_revert_refuses_stale_content_before_snapshot(revision_flow):
    state, packets, snapshots = revision_flow
    preview = revisions.wp_revert_to_revision("example", 7, 90)
    packets.approve_packet(packets.open_packet("example", "Restore", target="post:7:content").id, "owner")
    state["content"] = "Human edit"
    with pytest.raises(ConflictError):
        revisions.wp_revert_to_revision("example", 7, 90, apply=True, expected_etag=preview["etag"])
    assert state["writes"] == []
    assert snapshots.list_all() == []
