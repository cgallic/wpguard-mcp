"""Local site registry for wpguard-mcp.

Sites are registered once -- SSH connection info, or a companion-plugin URL
plus the name of an env var holding its API key -- and referenced by name
from every tool call afterwards. Secrets themselves live in environment
variables, never in the registry file, so `config/sites.json` is safe to
back up or inspect without leaking credentials (it is still gitignored as a
matter of policy, since host/path/username are still useful recon for an
attacker).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

STATE_DIR = Path(os.environ.get("WPGUARD_STATE_DIR", "state"))
DEFAULT_CONFIG_PATH = STATE_DIR / "config" / "sites.json"

VALID_TRANSPORTS = ("ssh", "companion_plugin")


class SiteNotFoundError(RuntimeError):
    pass


class SiteAlreadyExistsError(RuntimeError):
    pass


class InvalidSiteConfigError(RuntimeError):
    pass


@dataclass
class SiteConfig:
    name: str
    transport: str  # "ssh" or "companion_plugin"

    # --- ssh transport fields ---
    ssh_host: Optional[str] = None
    ssh_user: Optional[str] = None
    ssh_port: int = 22
    ssh_key_path: Optional[str] = None
    wp_path: Optional[str] = None  # remote path to the WP install, passed as wp-cli --path

    # --- companion_plugin transport fields ---
    plugin_url: Optional[str] = None  # e.g. https://example.com/wp-json/wpguard/v1/exec
    plugin_api_key_env: Optional[str] = None  # name of the env var holding the plugin API key

    notes: str = ""

    def __post_init__(self) -> None:
        if self.transport not in VALID_TRANSPORTS:
            raise InvalidSiteConfigError(
                f"transport must be one of {VALID_TRANSPORTS}, got '{self.transport}'"
            )
        if self.transport == "ssh" and not self.ssh_host:
            raise InvalidSiteConfigError("ssh transport requires ssh_host")
        if self.transport == "companion_plugin" and not (self.plugin_url and self.plugin_api_key_env):
            raise InvalidSiteConfigError(
                "companion_plugin transport requires plugin_url and plugin_api_key_env"
            )

    def to_dict(self) -> dict:
        return asdict(self)


class SiteRegistry:
    def __init__(self, path: Path | str = DEFAULT_CONFIG_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._sites: dict[str, SiteConfig] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        for name, entry in data.items():
            self._sites[name] = SiteConfig(**entry)

    def _save(self) -> None:
        data = {name: site.to_dict() for name, site in self._sites.items()}
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def register(self, site: SiteConfig, overwrite: bool = False) -> SiteConfig:
        if site.name in self._sites and not overwrite:
            raise SiteAlreadyExistsError(
                f"site '{site.name}' is already registered; pass overwrite=True to update it"
            )
        self._sites[site.name] = site
        self._save()
        return site

    def get(self, name: str) -> SiteConfig:
        site = self._sites.get(name)
        if site is None:
            raise SiteNotFoundError(f"no site registered as '{name}'; call site_register first")
        return site

    def list(self) -> list[SiteConfig]:
        return sorted(self._sites.values(), key=lambda s: s.name)

    def remove(self, name: str) -> None:
        if name in self._sites:
            del self._sites[name]
            self._save()


@lru_cache(maxsize=1)
def get_site_registry() -> SiteRegistry:
    return SiteRegistry()
