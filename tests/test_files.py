import pytest
from unittest.mock import patch
from wpguard_mcp.tools import files
from wpguard_mcp.guard import PacketStore, SnapshotStore, PacketRequiredError
from wpguard_mcp.config import SiteRegistry, SiteConfig

@pytest.fixture
def mock_stores(tmp_path):
    p_store = PacketStore(tmp_path / "packets.jsonl")
    s_store = SnapshotStore(tmp_path / "snapshots.jsonl")
    registry = SiteRegistry(tmp_path / "sites.json")
    registry.register(SiteConfig(name="test-plugin", transport="companion_plugin", plugin_url="https://example.com/wp-json/wpguard/v1/exec", plugin_api_key_env="DUMMY_KEY"))
    return p_store, s_store, registry

def test_file_read_plugin(mock_stores):
    p_store, s_store, registry = mock_stores
    mock_file = {"path": "wp-config.php", "content": "<?php // config", "total_lines": 1}
    with patch("wpguard_mcp.tools.files.get_site_registry", return_value=registry), \
         patch("wpguard_mcp.transports.companion_plugin.call", return_value=mock_file):
        res = files.wp_file_read("test-plugin", "wp-config.php")
        assert res["file"]["content"] == "<?php // config"

def test_file_write_dry_run_diff(mock_stores):
    p_store, s_store, registry = mock_stores
    with patch("wpguard_mcp.tools.files.get_site_registry", return_value=registry), \
         patch("wpguard_mcp.transports.companion_plugin.call", return_value={"previous_content": "line1\n"}):
        res = files.wp_file_write("test-plugin", "test.txt", "line1\nline2\n", apply=False)
        assert res["dry_run"] is True
        assert "+line2" in res["diff"]

def test_file_write_applied_takes_snapshot(mock_stores):
    p_store, s_store, registry = mock_stores
    p = p_store.open_packet("test-plugin", "write test file")
    p_store.approve_packet(p.id, approver="tester")
    with patch("wpguard_mcp.tools.files.get_site_registry", return_value=registry), \
         patch("wpguard_mcp.tools.files.get_packet_store", return_value=p_store), \
         patch("wpguard_mcp.tools.files.get_snapshot_store", return_value=s_store), \
         patch("wpguard_mcp.transports.companion_plugin.call", return_value={"previous_content": "old data"}):
        res = files.wp_file_write("test-plugin", "test.txt", "new data", apply=True)
        assert res["applied"] is True
        snapshots = s_store.list_for_packet(p.id)
        assert len(snapshots) == 1
        assert snapshots[0].previous_value == "old data"
