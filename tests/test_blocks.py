import pytest
from unittest.mock import patch
from wpguard_mcp.tools import blocks
from wpguard_mcp.guard import PacketStore
from wpguard_mcp.config import SiteRegistry, SiteConfig

@pytest.fixture
def mock_stores(tmp_path):
    p_store = PacketStore(tmp_path / "packets.jsonl")
    registry = SiteRegistry(tmp_path / "sites.json")
    registry.register(SiteConfig(name="test-plugin", transport="companion_plugin", plugin_url="https://example.com/wp-json/wpguard/v1/exec", plugin_api_key_env="DUMMY_KEY"))
    return p_store, registry

def test_block_validation():
    valid_markup = "<!-- wp:paragraph --><p>Hello</p><!-- /wp:paragraph -->"
    res = blocks.wp_block_validate("test-plugin", valid_markup)
    assert res["valid"] is True
    assert res["open_block_tags"] == 1

def test_post_create_dry_run_and_apply(mock_stores):
    p_store, registry = mock_stores
    p = p_store.open_packet("test-plugin", "create post")
    p_store.approve_packet(p.id, approver="tester")
    with patch("wpguard_mcp.tools.blocks.get_site_registry", return_value=registry), \
         patch("wpguard_mcp.tools.blocks.get_packet_store", return_value=p_store), \
         patch("wpguard_mcp.transports.companion_plugin.call", return_value={"post_id": 42, "url": "https://example.com/p/42"}):
        preview = blocks.wp_post_create("test-plugin", "New Landing Page", "<!-- wp:heading --><h2>Title</h2><!-- /wp:heading -->", apply=False)
        assert preview["dry_run"] is True
        
        applied = blocks.wp_post_create("test-plugin", "New Landing Page", "<!-- wp:heading --><h2>Title</h2><!-- /wp:heading -->", apply=True)
        assert applied["applied"] is True
        assert applied["result"]["post_id"] == 42
