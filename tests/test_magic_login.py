import pytest
from unittest.mock import patch
from wpguard_mcp.tools import magic_login
from wpguard_mcp.config import SiteRegistry, SiteConfig

def test_magic_login_plugin(tmp_path):
    registry = SiteRegistry(tmp_path / "sites.json")
    registry.register(SiteConfig(name="test-plugin", transport="companion_plugin", plugin_url="https://example.com/wp-json/wpguard/v1/exec", plugin_api_key_env="DUMMY_KEY"))
    mock_login = {"login_url": "https://example.com/wp-login.php?wpguard_magic=xyz", "expires_in": 600}
    with patch("wpguard_mcp.tools.magic_login.get_site_registry", return_value=registry), \
         patch("wpguard_mcp.transports.companion_plugin.call", return_value=mock_login):
        res = magic_login.wp_magic_login("test-plugin", user_login="admin")
        assert "login_url" in res["magic_login"]
