import pytest
from unittest.mock import patch
from wpguard_mcp.tools import skills
from wpguard_mcp.config import SiteRegistry, SiteConfig

def test_skills_save_and_get(tmp_path):
    registry = SiteRegistry(tmp_path / "sites.json")
    registry.register(SiteConfig(name="test-plugin", transport="companion_plugin", plugin_url="https://example.com/wp-json/wpguard/v1/exec", plugin_api_key_env="DUMMY_KEY"))
    with patch("wpguard_mcp.tools.skills.get_site_registry", return_value=registry), \
         patch("wpguard_mcp.transports.companion_plugin.call", return_value={"name": "seo-rules", "content": "# Rules"}):
        res = skills.wp_skill_get("test-plugin", "seo-rules")
        assert res["skill"]["name"] == "seo-rules"

def test_design_context(tmp_path):
    registry = SiteRegistry(tmp_path / "sites.json")
    registry.register(SiteConfig(name="test-plugin", transport="companion_plugin", plugin_url="https://example.com/wp-json/wpguard/v1/exec", plugin_api_key_env="DUMMY_KEY"))
    mock_ctx = {"theme_name": "Twentytwentyfour", "color_palette": [{"slug": "primary", "color": "#000"}]}
    with patch("wpguard_mcp.tools.skills.get_site_registry", return_value=registry), \
         patch("wpguard_mcp.transports.companion_plugin.call", return_value=mock_ctx):
        res = skills.wp_design_context("test-plugin")
        assert res["design_context"]["theme_name"] == "Twentytwentyfour"
