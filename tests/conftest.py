"""Shared fixtures: isolated stores + a fake SSH transport so the Tier 2/3
tools can be exercised without a real WordPress site.
"""
from __future__ import annotations

import pytest

from wpguard_mcp.config import SiteConfig
from wpguard_mcp.guard import PacketStore, SnapshotStore
from wpguard_mcp.transports import ssh_wpcli


class FakeRegistry:
    def __init__(self, site: SiteConfig):
        self._site = site

    def get(self, name: str) -> SiteConfig:
        return self._site


@pytest.fixture()
def ssh_site() -> SiteConfig:
    return SiteConfig(name="example", transport="ssh", ssh_host="example.com", ssh_user="deploy")


@pytest.fixture()
def stores(tmp_path):
    return PacketStore(path=tmp_path / "packets.jsonl"), SnapshotStore(path=tmp_path / "snapshots.jsonl")


@pytest.fixture()
def wired(monkeypatch, ssh_site, stores):
    """Wire the mutate/packets tool modules to isolated stores + fake SSH reads.

    `values` maps a wp-cli read to the string it should return; the fake write
    path records what would have been written into `writes`.
    """
    from wpguard_mcp.tools import mutate, packets

    packet_store, snapshot_store = stores
    registry = FakeRegistry(ssh_site)

    monkeypatch.setattr(mutate, "get_site_registry", lambda: registry)
    monkeypatch.setattr(mutate, "get_packet_store", lambda: packet_store)
    monkeypatch.setattr(mutate, "get_snapshot_store", lambda: snapshot_store)
    monkeypatch.setattr(packets, "get_site_registry", lambda: registry)
    monkeypatch.setattr(packets, "get_packet_store", lambda: packet_store)
    monkeypatch.setattr(packets, "get_snapshot_store", lambda: snapshot_store)

    state = {"values": {}, "writes": [], "eval_calls": []}

    def fake_run_wp_cli(site, args, timeout=60):
        # Reads: option get / post meta get / post get --field=content
        if args[:2] == ["option", "get"]:
            return ssh_wpcli.CommandResult(0, state["values"].get(("option", args[2]), ""), "")
        if args[:3] == ["post", "meta", "get"]:
            key = ("post_meta", int(args[3]), args[4])
            return ssh_wpcli.CommandResult(0, state["values"].get(key, ""), "")
        if args[:2] == ["post", "get"] and any(a.startswith("--field=content") for a in args):
            return ssh_wpcli.CommandResult(0, state["values"].get(("content", int(args[2])), ""), "")
        # Writes
        state["writes"].append(args)
        return ssh_wpcli.CommandResult(0, "", "")

    def fake_run_wp_cli_json(site, args, timeout=60):
        return []

    def fake_run_eval(site, php_code, timeout=60):
        state["eval_calls"].append(php_code)
        return ssh_wpcli.CommandResult(0, "ok", "")

    monkeypatch.setattr(ssh_wpcli, "run_wp_cli", fake_run_wp_cli)
    monkeypatch.setattr(ssh_wpcli, "run_wp_cli_json", fake_run_wp_cli_json)
    monkeypatch.setattr(ssh_wpcli, "run_eval", fake_run_eval)

    return {"packet_store": packet_store, "snapshot_store": snapshot_store, "state": state}
