"""Issue #12: Bedrock/Composer layout support on the site registry + wp-cli path."""
from __future__ import annotations

import pytest

from wpguard_mcp.config import InvalidSiteConfigError, SiteConfig


def test_classic_layout_uses_wp_path_directly():
    site = SiteConfig(name="s", transport="ssh", ssh_host="h", wp_path="/var/www/site")
    assert site.layout == "classic"
    assert site.effective_wp_path() == "/var/www/site"


def test_bedrock_layout_resolves_web_wp():
    site = SiteConfig(name="s", transport="ssh", ssh_host="h", wp_path="/var/www/site", layout="bedrock")
    assert site.effective_wp_path() == "/var/www/site/web/wp"


def test_bedrock_layout_strips_trailing_slash():
    site = SiteConfig(name="s", transport="ssh", ssh_host="h", wp_path="/var/www/site/", layout="bedrock")
    assert site.effective_wp_path() == "/var/www/site/web/wp"


def test_effective_wp_path_none_when_unset():
    site = SiteConfig(name="s", transport="ssh", ssh_host="h")
    assert site.effective_wp_path() is None


def test_invalid_layout_rejected():
    with pytest.raises(InvalidSiteConfigError):
        SiteConfig(name="s", transport="ssh", ssh_host="h", layout="nonsense")


def test_bedrock_path_flows_into_wp_cli_command(monkeypatch):
    from wpguard_mcp.transports import ssh_wpcli

    site = SiteConfig(name="s", transport="ssh", ssh_host="h", wp_path="/srv/app", layout="bedrock")

    captured = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return _Proc()

    monkeypatch.setattr(ssh_wpcli.subprocess, "run", fake_run)
    ssh_wpcli.run_wp_cli(site, ["option", "get", "blogname"])

    # The remote command string is the last ssh arg; it must point --path at web/wp.
    remote_command = captured["cmd"][-1]
    assert "--path=/srv/app/web/wp" in remote_command
