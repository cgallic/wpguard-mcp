from unittest.mock import call, patch

import pytest

from wpguard_mcp.config import SiteConfig, SiteRegistry
from wpguard_mcp.guard import ConflictError, PacketStore, SnapshotStore
from wpguard_mcp.tools import rollback


def test_rollback_option(tmp_path):
    p_store = PacketStore(tmp_path / "packets.jsonl")
    s_store = SnapshotStore(tmp_path / "snapshots.jsonl")
    registry = SiteRegistry(tmp_path / "sites.json")
    registry.register(
        SiteConfig(
            name="test-plugin",
            transport="companion_plugin",
            plugin_url="https://example.com/wp-json/wpguard/v1/exec",
            plugin_api_key_env="DUMMY_KEY",
        )
    )

    p = p_store.open_packet("test-plugin", "initial packet")
    p_store.approve_packet(p.id, approver="tester")
    snap = s_store.record(
        packet_id=p.id,
        site="test-plugin",
        tool="wp_mutate_option",
        target="option:blogname",
        previous_value="Old Site Title",
        new_value="New Site Title",
    )

    plugin_call = patch(
        "wpguard_mcp.transports.companion_plugin.call",
        side_effect=[{"option_name": "blogname", "value": "New Site Title"}, {"updated": True}],
    )
    with (
        patch("wpguard_mcp.tools.rollback.get_snapshot_store", return_value=s_store),
        patch("wpguard_mcp.tools.rollback.get_packet_store", return_value=p_store),
        patch("wpguard_mcp.tools.rollback.get_site_registry", return_value=registry),
        plugin_call as mocked_call,
    ):
        # Dry-run
        preview = rollback.wp_rollback("test-plugin", snap.id, apply=False)
        assert preview["dry_run"] is True
        assert preview["will_restore_value"] == "Old Site Title"

        # Apply
        applied = rollback.wp_rollback("test-plugin", snap.id, apply=True)
        assert applied["applied"] is True
        assert applied["restored_target"] == "option:blogname"
        assert mocked_call.call_args_list == [
            call(registry.get("test-plugin"), "get_option", {"option_name": "blogname"}),
            call(
                registry.get("test-plugin"),
                "update_option",
                {
                    "option_name": "blogname",
                    "new_value": "Old Site Title",
                    "expected_value_sha256": rollback._sha256("New Site Title"),
                },
            ),
        ]


def test_rollback_refuses_to_erase_newer_option_edit(tmp_path):
    p_store = PacketStore(tmp_path / "packets.jsonl")
    s_store = SnapshotStore(tmp_path / "snapshots.jsonl")
    registry = SiteRegistry(tmp_path / "sites.json")
    registry.register(SiteConfig(
        name="test", transport="companion_plugin", plugin_url="https://example.test", plugin_api_key_env="DUMMY_KEY"
    ))
    packet = p_store.open_packet("test", "rollback", target="option:blogname")
    p_store.approve_packet(packet.id, approver="tester")
    snap = s_store.record(
        packet_id=packet.id,
        site="test",
        tool="wp_mutate_option",
        target="option:blogname",
        previous_value="old",
        new_value="wpguard write",
    )
    with (
        patch("wpguard_mcp.tools.rollback.get_snapshot_store", return_value=s_store),
        patch("wpguard_mcp.tools.rollback.get_packet_store", return_value=p_store),
        patch("wpguard_mcp.tools.rollback.get_site_registry", return_value=registry),
        patch("wpguard_mcp.transports.companion_plugin.call", return_value={"value": "later human edit"}) as mocked,
    ):
        with pytest.raises(ConflictError, match="newer edits are preserved"):
            rollback.wp_rollback("test", snap.id, apply=True)
        assert mocked.call_count == 1


@pytest.mark.parametrize("source_tool", ["wp_mutate_post_content", "wp_page_replace_content"])
def test_companion_content_rollback_uses_atomic_full_replacement(tmp_path, source_tool):
    p_store = PacketStore(tmp_path / "packets.jsonl")
    s_store = SnapshotStore(tmp_path / "snapshots.jsonl")
    registry = SiteRegistry(tmp_path / "sites.json")
    registry.register(SiteConfig(
        name="test", transport="companion_plugin", plugin_url="https://example.test", plugin_api_key_env="DUMMY_KEY"
    ))
    packet = p_store.open_packet("test", "rollback", target="post:42:content")
    p_store.approve_packet(packet.id, approver="tester")
    snap = s_store.record(
        packet_id=packet.id,
        site="test",
        tool=source_tool,
        target="post:42:content",
        previous_value="before",
        new_value="after",
    )
    with (
        patch("wpguard_mcp.tools.rollback.get_snapshot_store", return_value=s_store),
        patch("wpguard_mcp.tools.rollback.get_packet_store", return_value=p_store),
        patch("wpguard_mcp.tools.rollback.get_site_registry", return_value=registry),
        patch("wpguard_mcp.transports.companion_plugin.call", return_value={"updated": True}) as mocked,
    ):
        result = rollback.wp_rollback("test", snap.id, apply=True)
    assert result["applied"] is True
    mocked.assert_called_once_with(
        registry.get("test"),
        "page_replace_content",
        {
            "post_id": 42,
            "new_content": "before",
            "expected_content_sha256": rollback._sha256("after"),
        },
    )
