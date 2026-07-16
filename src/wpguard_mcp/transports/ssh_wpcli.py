"""SSH + WP-CLI transport.

Shells out to the system `ssh` binary and runs `wp` on the remote host,
rather than reimplementing SSH with paramiko. This picks up the operator's
normal SSH config (~/.ssh/config, agent forwarding, ProxyJump, known_hosts)
for free, and keeps the dependency surface small.

This is the only transport allowed to reach Tier 3 (`wp_eval` / raw WP-CLI).
The companion-plugin transport never gets an eval capability -- see
transports/companion_plugin.py and wp-plugin/wpguard-companion.php.
"""
from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass

from ..config import SiteConfig


class SSHCommandError(RuntimeError):
    def __init__(self, message: str, returncode: int, stdout: str, stderr: str):
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _build_ssh_command(site: SiteConfig, remote_command: str) -> list[str]:
    if not site.ssh_host:
        raise ValueError(f"site '{site.name}' has no ssh_host configured")
    target = f"{site.ssh_user}@{site.ssh_host}" if site.ssh_user else site.ssh_host
    cmd = ["ssh", "-o", "BatchMode=yes", "-p", str(site.ssh_port)]
    if site.ssh_key_path:
        cmd += ["-i", site.ssh_key_path]
    cmd += [target, remote_command]
    return cmd


def run_wp_cli(site: SiteConfig, args: list[str], timeout: int = 60) -> CommandResult:
    """Run `wp <args...>` on `site` over SSH and return the raw result.

    `args` are the arguments after `wp`, e.g. ["option", "get", "blogname"].
    Automatically appends --path=<site.wp_path> when the site config declares
    one and the caller hasn't already passed --path themselves.
    """
    parts = ["wp"] + [shlex.quote(a) for a in args]
    if site.wp_path and not any(a.startswith("--path=") for a in args):
        parts.append(f"--path={shlex.quote(site.wp_path)}")
    remote_command = " ".join(parts)
    ssh_cmd = _build_ssh_command(site, remote_command)
    proc = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
    result = CommandResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    if not result.ok:
        raise SSHCommandError(
            f"wp-cli command failed on '{site.name}': wp {' '.join(args)}",
            result.returncode,
            result.stdout,
            result.stderr,
        )
    return result


def run_wp_cli_json(site: SiteConfig, args: list[str], timeout: int = 60) -> object:
    """Run a wp-cli command that supports --format=json and parse the result."""
    if not any(a.startswith("--format=") for a in args):
        args = [*args, "--format=json"]
    result = run_wp_cli(site, args, timeout=timeout)
    text = result.stdout.strip()
    if not text:
        return None
    return json.loads(text)


def run_eval(site: SiteConfig, php_code: str, timeout: int = 60) -> CommandResult:
    """Tier 3 escape hatch: `wp eval <php_code>` on the site.

    SSH-only by construction -- there is no equivalent call in
    transports/companion_plugin.py, and tools/mutate.py refuses to route
    wp_eval through a companion_plugin-transport site.
    """
    return run_wp_cli(site, ["eval", php_code], timeout=timeout)
