"""HTTPS transport to the wpguard companion WordPress plugin.

Used for sites where SSH access isn't available. The plugin exposes one REST
route (`/wp-json/wpguard/v1/exec`) that accepts a whitelisted command name
plus JSON args and returns a JSON result. There is deliberately no raw-PHP or
arbitrary-eval command on this transport -- see
wp-plugin/wpguard-companion.php and its ALLOWED_COMMANDS whitelist. If you
need Tier 3 (`wp_eval`), the site must be registered with the ssh transport
instead.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from ..config import SiteConfig

# Keep this in sync with the ALLOWED_COMMANDS whitelist in
# wp-plugin/wpguard-companion.php.
ALLOWED_COMMANDS = {
    "recon",
    "get_option",
    "update_option",
    "get_post_meta",
    "update_post_meta",
    "search_replace_post_content",
    "cache_flush",
}


class CompanionPluginError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _resolve_api_key(site: SiteConfig) -> str:
    if not site.plugin_api_key_env:
        raise ValueError(f"site '{site.name}' has no plugin_api_key_env configured")
    key = os.environ.get(site.plugin_api_key_env, "")
    if not key:
        raise ValueError(
            f"env var '{site.plugin_api_key_env}' is not set; cannot authenticate to the "
            f"companion plugin on '{site.name}'"
        )
    return key


def call(site: SiteConfig, command: str, args: Optional[dict[str, Any]] = None, timeout: float = 30.0) -> Any:
    """POST a whitelisted command to the companion plugin's REST route."""
    if command not in ALLOWED_COMMANDS:
        raise ValueError(f"'{command}' is not an allowed companion-plugin command")
    if not site.plugin_url:
        raise ValueError(f"site '{site.name}' has no plugin_url configured")

    api_key = _resolve_api_key(site)
    payload = {"command": command, "args": args or {}}
    headers = {"X-WPGuard-Key": api_key, "Content-Type": "application/json"}

    response = httpx.post(site.plugin_url, json=payload, headers=headers, timeout=timeout)

    if response.status_code == 401:
        raise CompanionPluginError(f"companion plugin rejected the API key for '{site.name}'", 401)
    if response.status_code == 400:
        raise CompanionPluginError(f"companion plugin rejected command '{command}': {response.text}", 400)
    if response.status_code >= 400:
        raise CompanionPluginError(
            f"companion plugin call failed ({response.status_code}) for '{site.name}': {response.text}",
            response.status_code,
        )

    data = response.json()
    if isinstance(data, dict) and data.get("ok") is False:
        raise CompanionPluginError(f"companion plugin reported an error: {data.get('error')}")
    return data.get("result") if isinstance(data, dict) else data
