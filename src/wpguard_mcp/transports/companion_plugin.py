"""HTTPS transport to the wpguard companion WordPress plugin.

Used for sites where SSH access isn't available. The plugin exposes one REST
route (`/wp-json/wpguard/v1/exec`) that accepts a whitelisted command name
plus JSON args and returns a JSON result. The whitelist includes powerful
administrative operations, so use a dedicated WordPress Application Password
and keep the route restricted to trusted operators.
"""
from __future__ import annotations

import os
from typing import Any

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
    "page_list",
    "page_get",
    "page_replace_content",
    "post_content_get",
    "post_content_replace",
    "revision_list",
    "revision_get",
    "revision_find",
    "revision_revert",
    "cache_flush",
    "eval_sandbox",
    "file_read",
    "file_write",
    "file_edit",
    "file_tree",
    "file_delete",
    "snippet_save",
    "snippet_toggle",
    "snippet_list",
    "block_parse",
    "block_compose",
    "post_create",
    "magic_login",
    "skill_save",
    "skill_get",
    "skill_list",
    "design_context",
    "schema_recon",
    "db_query",
}


class CompanionPluginError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
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


def _resolve_auth(site: SiteConfig) -> tuple[dict[str, str], httpx.BasicAuth | None]:
    if site.plugin_auth_mode == "application_password":
        if not site.wp_username or not site.wp_app_password_env:
            raise ValueError(f"site '{site.name}' has incomplete Application Password configuration")
        password = os.environ.get(site.wp_app_password_env, "")
        if not password:
            raise ValueError(
                f"env var '{site.wp_app_password_env}' is not set; cannot authenticate to '{site.name}'"
            )
        return {"Content-Type": "application/json"}, httpx.BasicAuth(site.wp_username, password)
    return {"X-WPGuard-Key": _resolve_api_key(site), "Content-Type": "application/json"}, None


def call(site: SiteConfig, command: str, args: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
    """POST a whitelisted command to the companion plugin's REST route."""
    if command not in ALLOWED_COMMANDS:
        raise ValueError(f"'{command}' is not an allowed companion-plugin command")
    if not site.plugin_url:
        raise ValueError(f"site '{site.name}' has no plugin_url configured")

    payload = {"command": command, "args": args or {}}
    headers, auth = _resolve_auth(site)

    response = httpx.post(site.plugin_url, json=payload, headers=headers, auth=auth, timeout=timeout)

    if response.status_code == 401:
        raise CompanionPluginError(f"companion plugin rejected authentication for '{site.name}'", 401)
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
    # Current companion routes return direct WP_REST_Response payloads;
    # older bridges wrap the payload in a result envelope.
    return data["result"] if isinstance(data, dict) and "result" in data else data
