from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from wpguard_mcp import corrections
from wpguard_mcp.config import SiteConfig
from wpguard_mcp.corrections import CorrectionBlockedError, CorrectionStore
from wpguard_mcp.guard import ConflictError, PacketStore, SnapshotStore
from wpguard_mcp.tools import blocks


@pytest.fixture()
def block_flow(monkeypatch, tmp_path):
    site = SiteConfig(
        name="example",
        transport="companion_plugin",
        plugin_url="https://example.test/wp-json/wpguard/v1/exec",
        plugin_api_key_env="TEST_KEY",
    )
    packet_store = PacketStore(tmp_path / "packets.jsonl")
    snapshot_store = SnapshotStore(tmp_path / "snapshots.jsonl")
    correction_store = CorrectionStore(tmp_path / "corrections.jsonl")
    monkeypatch.setattr(blocks, "get_site_registry", lambda: SimpleNamespace(get=lambda _name: site))
    monkeypatch.setattr(blocks, "get_packet_store", lambda: packet_store)
    monkeypatch.setattr(blocks, "get_snapshot_store", lambda: snapshot_store)
    monkeypatch.setattr(corrections, "get_correction_store", lambda: correction_store)
    monkeypatch.delenv("WPGUARD_BYPASS_GUARD", raising=False)
    state = {
        "content": '<!-- wp:paragraph {"className":"old"} --><p>Old</p><!-- /wp:paragraph -->',
        "blocks": [
            {
                "blockName": "core/paragraph",
                "attrs": {"className": "old", "clientId": "hero-copy"},
                "innerBlocks": [],
                "innerHTML": "<p>Old</p>",
                "innerContent": ["<p>Old</p>"],
            }
        ],
        "writes": [],
    }

    def call(_site, command, args=None):
        args = args or {}
        if command == "post_content_get":
            return {
                "id": 7,
                "post_type": "page",
                "title": "Target",
                "slug": "target",
                "status": "publish",
                "modified": "now",
                "url": "https://example.test/target/",
                "content": state["content"],
            }
        if command == "block_parse":
            return {"blocks": state["blocks"]}
        if command == "block_compose":
            block = args["blocks"][0]
            attrs = block["attrs"]
            html = block["innerHTML"]
            return {
                "markup": f'<!-- wp:paragraph {{"className":"{attrs["className"]}"}} -->'
                f"{html}<!-- /wp:paragraph -->"
            }
        if command == "post_content_replace":
            state["writes"].append(args)
            state["content"] = args["new_content"]
            return {"updated": True}
        if command == "revision_list":
            return {"revisions": [{"revision_id": 99}]}
        if command == "revision_find":
            assert args["exclude_revision_ids"] == [99]
            return {"revision_id": 101}
        raise AssertionError(command)

    monkeypatch.setattr(blocks.companion_plugin, "call", call)
    return state, packet_store, snapshot_store, correction_store


def test_block_preview_selects_client_id_and_returns_exact_review_data(block_flow):
    state, _, _, _ = block_flow
    preview = blocks.wp_mutate_block(
        "example",
        7,
        {"client_id": "hero-copy"},
        attrs_patch={"className": "approved"},
        inner_html="<p>Better</p>",
    )
    assert preview["dry_run"] is True
    assert preview["block"] == {"path": [0], "block_name": "core/paragraph"}
    assert preview["target"]["content_sha256"] == hashlib.sha256(state["content"].encode()).hexdigest()
    assert preview["proposed"]["content_sha256"]
    assert preview["diff"]["complete_sha256"]
    assert preview["corrections"]["status"] == "not_covered"


def test_block_apply_requires_exact_packet_and_returns_verified_revision(block_flow):
    state, packets, snapshots, _ = block_flow
    kwargs = {"site": "example", "post_id": 7, "selector": {"path": [0]}, "attrs_patch": {"className": "approved"}}
    preview = blocks.wp_mutate_block(**kwargs)
    packet = packets.open_packet(
        "example",
        "Update block",
        target="post:7:content",
        verb="wp_mutate_block",
        change_digest=preview["change_digest"],
    )
    packets.approve_packet(packet.id, "owner")
    result = blocks.wp_mutate_block(**kwargs, apply=True, expected_etag=preview["etag"])
    assert result["applied"] is True
    assert result["native_revision"] == {
        "supported": True,
        "revision_id": 101,
        "content_sha256": result["proposed"]["content_sha256"],
        "verified": True,
    }
    assert len(state["writes"]) == 1
    assert len(snapshots.list_for_packet(packet.id)) == 1


def test_block_apply_refuses_stale_etag_before_snapshot(block_flow):
    state, packets, snapshots, _ = block_flow
    preview = blocks.wp_mutate_block("example", 7, {"path": [0]}, attrs_patch={"className": "new"})
    packets.approve_packet(packets.open_packet("example", "Update", target="post:7:content").id, "owner")
    state["content"] = "Human edit"
    with pytest.raises(ConflictError):
        blocks.wp_mutate_block(
            "example", 7, {"path": [0]}, attrs_patch={"className": "new"}, apply=True, expected_etag=preview["etag"]
        )
    assert snapshots.list_all() == []


def test_block_apply_refuses_failed_correction(block_flow):
    state, packets, snapshots, correction_store = block_flow
    correction_store.record(
        site="example",
        target="post:7:content",
        human_correction="Keep approved text",
        source_ref="review:synthetic:1",
        human_requested_basis="Synthetic test request",
        kind="contains",
        expected="Approved text",
        rejected_value="Old",
        accepted_value="Approved text",
    )
    packets.approve_packet(packets.open_packet("example", "Update", target="post:7:content").id, "owner")
    with pytest.raises(CorrectionBlockedError):
        blocks.wp_mutate_block("example", 7, {"path": [0]}, attrs_patch={"className": "new"}, apply=True)
    assert state["writes"] == []
    assert snapshots.list_all() == []


def test_block_selector_requires_unambiguous_match():
    tree = [
        {"blockName": "core/paragraph", "attrs": {}, "innerBlocks": []},
        {"blockName": "core/paragraph", "attrs": {}, "innerBlocks": []},
    ]
    with pytest.raises(ValueError, match="multiple"):
        blocks._select_block(tree, {"block_name": "core/paragraph"})
    path, _ = blocks._select_block(tree, {"block_name": "core/paragraph", "occurrence": 1})
    assert path == (1,)
