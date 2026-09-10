"""Exercise HTTP response shapes emitted by the companion plugin."""

from unittest.mock import patch

import httpx
import pytest

from wpguard_mcp.config import SiteConfig
from wpguard_mcp.transports import companion_plugin

PLUGIN_SOURCE = (
    __import__("pathlib").Path(__file__).resolve().parents[1] / "wp-plugin" / "wpguard-companion.php"
).read_text(encoding="utf-8")


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


def test_companion_supports_application_password(monkeypatch):
    monkeypatch.setenv("TEST_APP_PASSWORD", "abcd efgh ijkl")
    site = SiteConfig(
        name="fixture",
        transport="companion_plugin",
        plugin_url="https://example.test/wp-json/wpguard/v1/exec",
        plugin_auth_mode="application_password",
        wp_username="operator",
        wp_app_password_env="TEST_APP_PASSWORD",
    )
    with patch.object(companion_plugin.httpx, "post", return_value=httpx.Response(200, json={"ok": True})) as post:
        companion_plugin.call(site, "recon")
    assert isinstance(post.call_args.kwargs["auth"], httpx.BasicAuth)
    assert "X-WPGuard-Key" not in post.call_args.kwargs["headers"]


def test_plugin_accepts_authenticated_administrator_before_legacy_key():
    assert "is_user_logged_in() && current_user_can( 'manage_options' )" in PLUGIN_SOURCE
