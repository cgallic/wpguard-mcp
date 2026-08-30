import pytest
from unittest.mock import patch
from wpguard_mcp.tools import eval_sandbox
from wpguard_mcp.guard import PacketStore, SnapshotStore, PacketRequiredError
from wpguard_mcp.config import SiteRegistry, SiteConfig

@pytest.fixture
def mock_stores(tmp_path):
    p_store = PacketStore(tmp_path / "packets.jsonl")
    s_store = SnapshotStore(tmp_path / "snapshots.jsonl")
    registry = SiteRegistry(tmp_path / "sites.json")
    registry.register(SiteConfig(name="test-ssh", transport="ssh", ssh_host="example.com"))
    registry.register(SiteConfig(name="test-plugin", transport="companion_plugin", plugin_url="https://example.com/wp-json/wpguard/v1/exec", plugin_api_key_env="DUMMY_KEY"))
    return p_store, s_store, registry

def test_eval_sandbox_dry_run(mock_stores):
    p_store, s_store, registry = mock_stores
    with patch("wpguard_mcp.tools.eval_sandbox.get_site_registry", return_value=registry):
        res = eval_sandbox.wp_eval_sandbox("test-plugin", "echo 123;", apply=False)
        assert res["dry_run"] is True
        assert res["applied"] is False

def test_eval_sandbox_requires_packet(mock_stores):
    p_store, s_store, registry = mock_stores
    with patch("wpguard_mcp.tools.eval_sandbox.get_site_registry", return_value=registry), \
         patch("wpguard_mcp.tools.eval_sandbox.get_packet_store", return_value=p_store):
        with pytest.raises(PacketRequiredError):
            eval_sandbox.wp_eval_sandbox("test-plugin", "echo 123;", apply=True)

def test_eval_sandbox_applied_plugin(mock_stores):
    p_store, s_store, registry = mock_stores
    pkt = p_store.open_packet("test-plugin", "test eval")
    p_store.approve_packet(pkt.id, approver="tester")
    mock_res = {"success": True, "output": "123", "return_value": None, "error": None, "duration_ms": 1.5}
    with patch("wpguard_mcp.tools.eval_sandbox.get_site_registry", return_value=registry), \
         patch("wpguard_mcp.tools.eval_sandbox.get_packet_store", return_value=p_store), \
         patch("wpguard_mcp.transports.companion_plugin.call", return_value=mock_res):
        res = eval_sandbox.wp_eval_sandbox("test-plugin", "echo 123;", apply=True)
        assert res["applied"] is True
        assert res["result"]["output"] == "123"

def test_snippet_save_and_toggle(mock_stores):
    p_store, s_store, registry = mock_stores
    pkt = p_store.open_packet("test-plugin", "test snippet")
    p_store.approve_packet(pkt.id, approver="tester")
    with patch("wpguard_mcp.tools.eval_sandbox.get_site_registry", return_value=registry), \
         patch("wpguard_mcp.tools.eval_sandbox.get_packet_store", return_value=p_store), \
         patch("wpguard_mcp.tools.eval_sandbox.get_snapshot_store", return_value=s_store), \
         patch("wpguard_mcp.transports.companion_plugin.call", return_value={"name": "custom-code", "active": True}):
        res = eval_sandbox.wp_snippet_save("test-plugin", "custom-code", "add_action('init', 'foo');", apply=True)
        assert res["applied"] is True
        assert res["name"] == "custom-code"
