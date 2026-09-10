from types import SimpleNamespace

from wpguard_mcp.config import SiteConfig
from wpguard_mcp.guard import PacketStore
from wpguard_mcp.tools import updates


class Registry:
    def __init__(self, site):
        self.site = site

    def get(self, name):
        return self.site


def setup_update(monkeypatch, tmp_path, health_fails=False):
    site = SiteConfig(name="example", transport="ssh", ssh_host="example.test")
    store = PacketStore(tmp_path / "packets.jsonl")
    state = {"version": "1.0", "writes": []}

    def run_json(config, args, timeout=60):
        return [{"name": "forms", "version": state["version"], "update_version": "2.0", "status": "active"}]

    def run(config, args, timeout=60):
        state["writes"].append(args)
        if args[:3] == ["plugin", "update", "forms"]:
            state["version"] = "2.0"
        elif args[:3] == ["plugin", "install", "forms"]:
            state["version"] = "1.0"
        if args[:2] == ["eval", "echo PHP_VERSION;"] and health_fails:
            raise RuntimeError("PHP fatal")
        stdout = (
            "8.3" if args[0] == "eval" else ("https://example.test" if args[:3] == ["option", "get", "siteurl"] else "")
        )
        return SimpleNamespace(stdout=stdout)

    monkeypatch.setattr(updates, "get_site_registry", lambda: Registry(site))
    monkeypatch.setattr(updates, "get_packet_store", lambda: store)
    monkeypatch.setattr(updates.ssh_wpcli, "run_wp_cli_json", run_json)
    monkeypatch.setattr(updates.ssh_wpcli, "run_wp_cli", run)
    monkeypatch.setattr(updates, "vulnerability_assessment", lambda *a, **k: {"status": "clean"})
    monkeypatch.setattr(updates.httpx, "get", lambda *a, **k: SimpleNamespace(status_code=200))
    return store, state


def test_plugin_update_preview_binds_exact_versions(monkeypatch, tmp_path):
    _, state = setup_update(monkeypatch, tmp_path)
    result = updates.wp_plugin_update("example", "forms")
    assert result["current_version"] == "1.0"
    assert result["target_version"] == "2.0"
    assert len(result["change_digest"]) == 64
    assert state["writes"] == []


def test_plugin_update_verifies_health(monkeypatch, tmp_path):
    store, state = setup_update(monkeypatch, tmp_path)
    preview = updates.wp_plugin_update("example", "forms")
    packet = store.open_packet(
        "example", "update", target="plugin:forms", verb="wp_plugin_update", change_digest=preview["change_digest"]
    )
    store.approve_packet(packet.id, "owner")
    result = updates.wp_plugin_update("example", "forms", apply=True, expected_version="1.0")
    assert result["applied"] is True
    assert result["new_version"] == "2.0"
    assert result["health"]["http_status"] == 200
    assert state["version"] == "2.0"


def test_failed_health_automatically_rolls_back(monkeypatch, tmp_path):
    store, state = setup_update(monkeypatch, tmp_path, health_fails=True)
    preview = updates.wp_plugin_update("example", "forms")
    packet = store.open_packet(
        "example", "update", target="plugin:forms", verb="wp_plugin_update", change_digest=preview["change_digest"]
    )
    store.approve_packet(packet.id, "owner")
    result = updates.wp_plugin_update("example", "forms", apply=True, expected_version="1.0")
    assert result["applied"] is False
    assert result["rolled_back"] is True
    assert state["version"] == "1.0"
    assert ["plugin", "install", "forms", "--version=1.0", "--force"] in state["writes"]
