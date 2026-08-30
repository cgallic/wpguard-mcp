import pytest
from unittest.mock import patch
from wpguard_mcp.tools import schema_recon
from wpguard_mcp.guard import PacketStore
from wpguard_mcp.config import SiteRegistry, SiteConfig

def test_schema_recon(tmp_path):
    registry = SiteRegistry(tmp_path / "sites.json")
    registry.register(SiteConfig(name="test-plugin", transport="companion_plugin", plugin_url="https://example.com/wp-json/wpguard/v1/exec", plugin_api_key_env="DUMMY_KEY"))
    mock_schema = {"post_types": ["post", "page", "product"], "taxonomies": ["category"], "builders": ["Elementor"]}
    with patch("wpguard_mcp.tools.schema_recon.get_site_registry", return_value=registry), \
         patch("wpguard_mcp.transports.companion_plugin.call", return_value=mock_schema):
        res = schema_recon.wp_schema_recon("test-plugin")
        assert "Elementor" in res["schema"]["builders"]

def test_db_query_select(tmp_path):
    registry = SiteRegistry(tmp_path / "sites.json")
    registry.register(SiteConfig(name="test-plugin", transport="companion_plugin", plugin_url="https://example.com/wp-json/wpguard/v1/exec", plugin_api_key_env="DUMMY_KEY"))
    mock_rows = [{"ID": "1", "post_title": "Hello"}]
    with patch("wpguard_mcp.tools.schema_recon.get_site_registry", return_value=registry), \
         patch("wpguard_mcp.transports.companion_plugin.call", return_value={"rows": mock_rows, "count": 1}):
        res = schema_recon.wp_db_query("test-plugin", "SELECT ID, post_title FROM wp_posts LIMIT 1")
        assert res["applied"] is True
