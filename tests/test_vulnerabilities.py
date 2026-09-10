
import pytest

from wpguard_mcp.config import SiteConfig
from wpguard_mcp.guard import PacketStore
from wpguard_mcp.tools import packets, vulnerabilities


class Registry:
    def get(self, name):
        return SiteConfig(name=name, transport="ssh", ssh_host="example.test")


class Provider:
    def __init__(self):
        self.calls = 0

    def check(self, kind, slug, version):
        self.calls += 1
        return {"status": "vulnerable", "vulnerabilities": [{"id": "TEST-1"}]}


def test_scan_caches_provider_result(monkeypatch, tmp_path):
    monkeypatch.setattr(vulnerabilities, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(vulnerabilities, "get_site_registry", lambda: Registry())
    monkeypatch.setattr(
        vulnerabilities.ssh_wpcli,
        "run_wp_cli_json",
        lambda config, args: ([{"name": "forms", "version": "1.0"}] if args[0] == "plugin" else []),
    )
    provider = Provider()
    first = vulnerabilities._scan("example", provider=provider)
    second = vulnerabilities._scan("example", provider=provider)
    assert first["status"] == "vulnerable"
    assert second["cached"] is True
    assert provider.calls == 1


def test_missing_provider_token_is_explicit_unknown(monkeypatch):
    monkeypatch.delenv(vulnerabilities.WPSCAN_TOKEN_ENV, raising=False)
    result = vulnerabilities.WPScanProvider().check("plugin", "forms", "1.0")
    assert result["status"] == "unknown"
    assert vulnerabilities.WPSCAN_TOKEN_ENV in result["reason"]


def test_block_policy_rejects_unknown(monkeypatch):
    monkeypatch.setenv(vulnerabilities.POLICY_ENV, "block")
    monkeypatch.setattr(
        vulnerabilities,
        "wp_vulnerability_scan",
        lambda *a, **k: {"findings": [{"kind": "plugin", "slug": "forms", "status": "unknown"}]},
    )
    with pytest.raises(vulnerabilities.VulnerabilityPolicyError, match="unknown"):
        vulnerabilities.enforce_packet_policy("example", "plugin:forms")


def test_packet_approval_returns_vulnerability_warning(monkeypatch, tmp_path):
    store = PacketStore(tmp_path / "packets.jsonl")
    packet = store.open_packet("example", "update forms", target="plugin:forms")
    monkeypatch.setattr(packets, "get_packet_store", lambda: store)
    monkeypatch.setattr(packets, "emit_event", lambda *args: None)
    monkeypatch.setattr(
        packets,
        "enforce_packet_policy",
        lambda site, target: {"status": "unknown", "policy": "warn", "warning": "vulnerability status is unknown"},
    )
    approved = packets.packet_approve(packet.id, "owner")
    assert approved["status"] == "approved"
    assert approved["vulnerability"]["warning"] == "vulnerability status is unknown"
