"""Unit tests for wpguard_mcp.config: the local site registry."""
from __future__ import annotations

import pytest

from wpguard_mcp.config import (
    InvalidSiteConfigError,
    SiteAlreadyExistsError,
    SiteConfig,
    SiteNotFoundError,
    SiteRegistry,
)


@pytest.fixture()
def registry(tmp_path):
    return SiteRegistry(path=tmp_path / "sites.json")


def test_register_and_get_ssh_site(registry):
    site = SiteConfig(name="example", transport="ssh", ssh_host="example.com", ssh_user="deploy")

    registry.register(site)
    fetched = registry.get("example")

    assert fetched.ssh_host == "example.com"
    assert fetched.ssh_user == "deploy"


def test_register_duplicate_without_overwrite_raises(registry):
    site = SiteConfig(name="example", transport="ssh", ssh_host="example.com")
    registry.register(site)

    with pytest.raises(SiteAlreadyExistsError):
        registry.register(SiteConfig(name="example", transport="ssh", ssh_host="example.com"))


def test_register_duplicate_with_overwrite_updates(registry):
    registry.register(SiteConfig(name="example", transport="ssh", ssh_host="old-host.com"))
    registry.register(SiteConfig(name="example", transport="ssh", ssh_host="new-host.com"), overwrite=True)

    assert registry.get("example").ssh_host == "new-host.com"


def test_get_unknown_site_raises(registry):
    with pytest.raises(SiteNotFoundError):
        registry.get("does-not-exist")


def test_ssh_transport_requires_ssh_host():
    with pytest.raises(InvalidSiteConfigError):
        SiteConfig(name="example", transport="ssh")


def test_companion_plugin_transport_requires_url_and_key_env():
    with pytest.raises(InvalidSiteConfigError):
        SiteConfig(name="example", transport="companion_plugin")


def test_companion_plugin_transport_valid():
    site = SiteConfig(
        name="example",
        transport="companion_plugin",
        plugin_url="https://example.com/wp-json/wpguard/v1/exec",
        plugin_api_key_env="WPGUARD_SITE_EXAMPLE_KEY",
    )
    assert site.plugin_url.endswith("/exec")


def test_registry_persists_across_instances(tmp_path):
    path = tmp_path / "sites.json"
    registry_a = SiteRegistry(path=path)
    registry_a.register(SiteConfig(name="example", transport="ssh", ssh_host="example.com"))

    registry_b = SiteRegistry(path=path)
    assert registry_b.get("example").ssh_host == "example.com"


def test_list_sites_sorted_by_name(registry):
    registry.register(SiteConfig(name="zeta", transport="ssh", ssh_host="z.com"))
    registry.register(SiteConfig(name="alpha", transport="ssh", ssh_host="a.com"))

    names = [s.name for s in registry.list()]
    assert names == ["alpha", "zeta"]
