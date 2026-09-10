"""Cached vulnerability intelligence with explicit unknown states."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx

from ..config import STATE_DIR, get_site_registry
from ..transports import companion_plugin, ssh_wpcli

WPSCAN_TOKEN_ENV = "WPGUARD_WPSCAN_API_TOKEN"
POLICY_ENV = "WPGUARD_VULNERABILITY_POLICY"
CACHE_TTL_ENV = "WPGUARD_VULNERABILITY_CACHE_TTL_SECONDS"
DEFAULT_CACHE_TTL = 86400
CACHE_DIR = STATE_DIR / "vulnerability-cache"


class VulnerabilityPolicyError(RuntimeError):
    pass


@dataclass
class WPScanProvider:
    token: str | None = None
    base_url: str = "https://wpscan.com/api/v3"

    def check(self, kind: str, slug: str, version: str) -> dict:
        token = self.token or os.environ.get(WPSCAN_TOKEN_ENV, "").strip()
        if not token:
            return {"status": "unknown", "reason": f"{WPSCAN_TOKEN_ENV} is not configured", "vulnerabilities": []}
        endpoint = "plugins" if kind == "plugin" else "themes"
        try:
            response = httpx.get(
                f"{self.base_url}/{endpoint}/{quote(slug, safe='')}/{quote(version, safe='')}",
                headers={"Authorization": f"Token token={token}"},
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            return {"status": "unknown", "reason": f"WPScan lookup failed: {exc}", "vulnerabilities": []}
        record = payload.get(slug, payload) if isinstance(payload, dict) else {}
        vulnerabilities = record.get("vulnerabilities", []) if isinstance(record, dict) else []
        return {"status": "vulnerable" if vulnerabilities else "clean", "vulnerabilities": vulnerabilities}


def _components(site_config) -> list[dict]:
    if site_config.transport == "ssh":
        plugin_result = ssh_wpcli.run_wp_cli_json(site_config, ["plugin", "list"])
        theme_result = ssh_wpcli.run_wp_cli_json(site_config, ["theme", "list"])
        plugins = plugin_result if isinstance(plugin_result, list) else []
        themes = theme_result if isinstance(theme_result, list) else []
        return [{"kind": "plugin", "slug": p.get("name"), "version": p.get("version")} for p in plugins] + [
            {"kind": "theme", "slug": t.get("name"), "version": t.get("version")} for t in themes
        ]
    recon_result = companion_plugin.call(site_config, "recon") or {}
    recon = recon_result if isinstance(recon_result, dict) else {}
    # The current companion recon does not expose reliable component versions.
    return [{"kind": "plugin", "slug": str(p), "version": None} for p in recon.get("active_plugins", [])]


def _cache_path(site: str) -> Path:
    import hashlib

    return CACHE_DIR / f"{hashlib.sha256(site.encode()).hexdigest()}.json"


def _ttl() -> int:
    try:
        return max(0, int(os.environ.get(CACHE_TTL_ENV, str(DEFAULT_CACHE_TTL))))
    except ValueError:
        return DEFAULT_CACHE_TTL


def _scan(site: str, refresh: bool = False, provider=None) -> dict:
    path = _cache_path(site)
    if not refresh and path.exists() and time.time() - path.stat().st_mtime <= _ttl():
        result = json.loads(path.read_text(encoding="utf-8"))
        return {**result, "cached": True}
    site_config = get_site_registry().get(site)
    checker = provider or WPScanProvider()
    findings = []
    for component in _components(site_config):
        if not component["slug"] or not component["version"]:
            check = {"status": "unknown", "reason": "component version is unavailable", "vulnerabilities": []}
        else:
            check = checker.check(component["kind"], str(component["slug"]), str(component["version"]))
        findings.append({**component, **check})
    statuses = {item["status"] for item in findings}
    status = "vulnerable" if "vulnerable" in statuses else ("unknown" if "unknown" in statuses else "clean")
    result = {
        "site": site,
        "status": status,
        "provider": "wpscan",
        "scanned_at": time.time(),
        "findings": findings,
        "cached": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def wp_vulnerability_scan(site: str, refresh: bool = False) -> dict:
    """Scan installed plugins/themes through WPScan, caching results for one day by default."""
    return _scan(site, refresh=refresh)


def vulnerability_assessment(site: str, target: str = "*", refresh: bool = False) -> dict:
    report = wp_vulnerability_scan(site, refresh=refresh)
    kind, _, slug = target.partition(":")
    findings = report["findings"]
    if kind in {"plugin", "theme"} and slug:
        findings = [f for f in findings if f["kind"] == kind and f["slug"] == slug]
    statuses = {f["status"] for f in findings}
    status = (
        "vulnerable" if "vulnerable" in statuses else ("unknown" if "unknown" in statuses or not findings else "clean")
    )
    mode = os.environ.get(POLICY_ENV, "warn").strip().lower()
    if mode not in {"off", "warn", "block"}:
        mode = "warn"
    return {
        "status": status,
        "policy": mode,
        "target": target,
        "warning": None if status == "clean" or mode == "off" else f"vulnerability status is {status}",
        "findings": findings,
    }


def enforce_packet_policy(site: str, target: str) -> dict:
    assessment = vulnerability_assessment(site, target=target)
    if assessment["policy"] == "block" and assessment["status"] != "clean":
        raise VulnerabilityPolicyError(
            f"packet approval blocked: vulnerability status for {target} is {assessment['status']}"
        )
    return assessment
