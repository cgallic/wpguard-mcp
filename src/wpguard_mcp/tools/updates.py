"""Guarded WordPress plugin and theme updates with automatic recovery."""

from __future__ import annotations

import hashlib

import httpx

from ..config import get_site_registry
from ..guard import build_change_digest, get_packet_store, require_approved_packet
from ..transports import ssh_wpcli
from .vulnerabilities import vulnerability_assessment


def _component(site_config, kind: str, slug: str) -> dict:
    rows = ssh_wpcli.run_wp_cli_json(site_config, [kind, "list"])
    items = rows if isinstance(rows, list) else []
    matches = [row for row in items if isinstance(row, dict) and row.get("name") == slug]
    if len(matches) != 1:
        raise ValueError(f"{kind} '{slug}' was not found or was ambiguous")
    return matches[0]


def _etag(kind: str, slug: str, version: str) -> str:
    return hashlib.sha256(f"{kind}:{slug}:{version}".encode()).hexdigest()[:16]


def _health(site_config) -> dict:
    php = ssh_wpcli.run_wp_cli(site_config, ["eval", "echo PHP_VERSION;"]).stdout.strip()
    ssh_wpcli.run_wp_cli(site_config, ["core", "is-installed"])
    url = ssh_wpcli.run_wp_cli(site_config, ["option", "get", "siteurl"]).stdout.strip()
    response = httpx.get(url, follow_redirects=True, timeout=20.0)
    if response.status_code >= 500:
        raise RuntimeError(f"site health request returned HTTP {response.status_code}")
    return {"php_version": php, "site_url": url, "http_status": response.status_code}


def _update(
    kind: str, site: str, slug: str, target_version: str | None, apply: bool, expected_version: str | None
) -> dict:
    site_config = get_site_registry().get(site)
    if site_config.transport != "ssh":
        raise ValueError("plugin and theme updates currently require the SSH transport")
    current = _component(site_config, kind, slug)
    current_version = str(current.get("version", ""))
    available = str(current.get("update_version") or "")
    desired = target_version or available
    if not desired:
        raise ValueError(f"no update is available for {kind} '{slug}'; pass target_version explicitly")
    target = f"{kind}:{slug}"
    payload = {"slug": slug, "target_version": desired}
    current_etag = _etag(kind, slug, current_version)
    digest = build_change_digest(site, f"wp_{kind}_update", target, current_etag, payload)
    security = vulnerability_assessment(site, target=target, refresh=False)
    preview = {
        "site": site,
        "kind": kind,
        "slug": slug,
        "current_version": current_version,
        "target_version": desired,
        "etag": current_etag,
        "change_digest": digest,
        "security": security,
        "dry_run": not apply,
        "applied": False,
    }
    if not apply:
        return preview
    if not expected_version:
        raise ValueError("expected_version from the preview is required")
    if expected_version != current_version:
        raise ValueError(
            f"{kind} version changed after preview "
            f"(expected {expected_version}, current {current_version}); preview again"
        )
    packet = require_approved_packet(get_packet_store(), site, target=target, change_digest=digest)
    args = [kind, "update", slug, f"--version={desired}"]
    try:
        ssh_wpcli.run_wp_cli(site_config, args, timeout=300)
        updated = _component(site_config, kind, slug)
        if str(updated.get("version", "")) != desired:
            raise RuntimeError(f"version read-back was {updated.get('version')}, expected {desired}")
        health = _health(site_config)
    except Exception as update_error:
        rollback_error = None
        try:
            ssh_wpcli.run_wp_cli(
                site_config, [kind, "install", slug, f"--version={current_version}", "--force"], timeout=300
            )
            restored = _component(site_config, kind, slug)
            if str(restored.get("version", "")) != current_version:
                raise RuntimeError(f"rollback read-back was {restored.get('version')}, expected {current_version}")
        except Exception as exc:
            rollback_error = str(exc)
        get_packet_store().log(
            packet.id,
            f"wp_{kind}_update failed: {update_error}; rollback "
            + (f"failed: {rollback_error}" if rollback_error else "verified"),
        )
        return {
            **preview,
            "dry_run": False,
            "error": str(update_error),
            "rolled_back": rollback_error is None,
            "rollback_error": rollback_error,
            "packet_id": packet.id,
        }
    get_packet_store().log(
        packet.id, f"applied wp_{kind}_update({slug}) {current_version} -> {desired}; health verified"
    )
    return {
        **preview,
        "dry_run": False,
        "applied": True,
        "previous_version": current_version,
        "new_version": desired,
        "health": health,
        "packet_id": packet.id,
    }


def wp_plugin_update(
    site: str, slug: str, target_version: str | None = None, apply: bool = False, expected_version: str | None = None
) -> dict:
    """Preview or apply one exact plugin update with health checks and automatic rollback."""
    return _update("plugin", site, slug, target_version, apply, expected_version)


def wp_theme_update(
    site: str, slug: str, target_version: str | None = None, apply: bool = False, expected_version: str | None = None
) -> dict:
    """Preview or apply one exact theme update with health checks and automatic rollback."""
    return _update("theme", site, slug, target_version, apply, expected_version)


GUARDED_TOOLS = {"wp_plugin_update": wp_plugin_update, "wp_theme_update": wp_theme_update}
