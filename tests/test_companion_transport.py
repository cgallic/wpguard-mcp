"""Exercise HTTP response shapes emitted by the companion plugin."""

from unittest.mock import patch

import httpx
import pytest

from wpguard_mcp.config import SiteConfig
from wpguard_mcp.transports import companion_plugin


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"wp_version": "6.8", "active_plugins": ["elementor/elementor.php"]},
         {"wp_version": "6.8", "active_plugins": ["elementor/elementor.php"]}),
        ({"ok": True, "result": {"wp_version": "6.8"}}, {"wp_version": "6.8"}),
        ({"ok": True, "result": False}, False),
        ({"ok": True, "result": None}, None),
        (["item"], ["item"]),
    ],
)
def test_companion_preserves_direct_and_wrapped_responses(monkeypatch, payload, expected):
    monkeypatch.setenv("TEST_COMPANION_KEY", "fixture-key")
    site = SiteConfig(
        name="fixture", transport="companion_plugin",
        plugin_url="https://example.test/wp-json/wpguard/v1/exec",
        plugin_api_key_env="TEST_COMPANION_KEY",
    )
    with patch.object(companion_plugin.httpx, "post", return_value=httpx.Response(200, json=payload)):
        assert companion_plugin.call(site, "recon") == expected


def test_companion_still_rejects_error_envelope(monkeypatch):
    monkeypatch.setenv("TEST_COMPANION_KEY", "fixture-key")
    site = SiteConfig(
        name="fixture", transport="companion_plugin",
        plugin_url="https://example.test/wp-json/wpguard/v1/exec",
        plugin_api_key_env="TEST_COMPANION_KEY",
    )
    response = httpx.Response(200, json={"ok": False, "error": "denied"})
    with patch.object(companion_plugin.httpx, "post", return_value=response):
        with pytest.raises(companion_plugin.CompanionPluginError, match="denied"):
            companion_plugin.call(site, "recon")
