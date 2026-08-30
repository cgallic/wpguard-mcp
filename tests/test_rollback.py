import pytest
from unittest.mock import patch
from wpguard_mcp.tools import rollback
from wpguard_mcp.guard import PacketStore, SnapshotStore
from wpguard_mcp.config import SiteRegistry, SiteConfig

def test_rollback_option(tmp_path):
    p_store = PacketStore(tmp_path / "packets.jsonl")
    s_store = SnapshotStore(tmp_path / "snapshots.jsonl")
    registry = SiteRegistry(tmp_path / "sites.json")
    registry.register(SiteConfig(name="test-plugin", transport="companion_plugin", plugin_url="https://example.com/wp-json/wpguard/v1/exec", plugin_api_key_env="DUMMY_KEY"))
    
    p = p_store.open_packet("test-plugin", "initial packet")
    p_store.approve_packet(p.id, approver="tester")
    snap = s_store.record(packet_id=p.id, site="test-plugin", tool="wp_mutate_option", target="blogname", previous_value="Old Site Title")
    
    with patch("wpguard_mcp.tools.rollback.get_snapshot_store", return_value=s_store), \
         patch("wpguard_mcp.tools.rollback.get_packet_store", return_value=p_store), \
         patch("wpguard_mcp.tools.rollback.get_site_registry", return_value=registry), \
         patch("wpguard_mcp.transports.companion_plugin.call", return_value=True):
        
        # Dry-run
        preview = rollback.wp_rollback("test-plugin", snap.id, apply=False)
        assert preview["dry_run"] is True
        assert preview["will_restore_value"] == "Old Site Title"
        
        # Apply
        applied = rollback.wp_rollback("test-plugin", snap.id, apply=True)
        assert applied["applied"] is True
        assert applied["restored_target"] == "blogname"
