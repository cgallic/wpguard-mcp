"""WP-CLI execution and asynchronous background task runner."""
from __future__ import annotations

import uuid
from typing import Sequence

from ..config import get_site_registry
from ..guard import get_packet_store, require_approved_packet
from ..transports import ssh_wpcli


def wp_cli_run(site: str, args: Sequence[str], apply: bool = False) -> dict:
    """Run a synchronous WP-CLI command (SSH transport only)."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport != "ssh":
        return {"error": "wp_cli_run is available only on SSH-configured sites"}

    if not apply:
        return {
            "site": site,
            "dry_run": True,
            "applied": False,
            "args": list(args),
            "command_preview": "wp " + " ".join(args),
        }

    packet = require_approved_packet(get_packet_store(), site)
    res = ssh_wpcli.run_wp_cli(site_config, args)
    get_packet_store().log(packet.id, f"applied wp_cli_run({' '.join(args)})")

    return {
        "site": site,
        "dry_run": False,
        "applied": True,
        "stdout": res.stdout,
        "stderr": res.stderr,
        "returncode": res.returncode,
        "packet_id": packet.id,
    }


def wp_cli_job_start(site: str, args: Sequence[str], apply: bool = False) -> dict:
    """Launch a long-running WP-CLI command in the background (SSH only)."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport != "ssh":
        return {"error": "wp_cli_job_start is available only on SSH-configured sites"}

    job_id = uuid.uuid4().hex[:10]
    log_file = f"/tmp/wpguard_job_{job_id}.log"
    pid_file = f"/tmp/wpguard_job_{job_id}.pid"

    if not apply:
        return {
            "site": site,
            "dry_run": True,
            "applied": False,
            "args": list(args),
            "log_file": log_file,
        }

    packet = require_approved_packet(get_packet_store(), site)
    cmd_str = "wp " + " ".join(args)
    launch_cmd = f"nohup {cmd_str} > {log_file} 2>&1 & echo $! > {pid_file}"
    ssh_wpcli.run_ssh_raw(site_config, launch_cmd)

    get_packet_store().log(packet.id, f"started background wp_cli_job {job_id} ({cmd_str})")
    return {
        "site": site,
        "job_id": job_id,
        "log_file": log_file,
        "pid_file": pid_file,
        "packet_id": packet.id,
        "status": "running",
    }


def wp_cli_job_status(site: str, job_id: str) -> dict:
    """Check the status and tail output logs of a background WP-CLI job."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport != "ssh":
        return {"error": "wp_cli_job_status is available only on SSH-configured sites"}

    log_file = f"/tmp/wpguard_job_{job_id}.log"
    pid_file = f"/tmp/wpguard_job_{job_id}.pid"

    pid_res = ssh_wpcli.run_ssh_raw(site_config, f"cat {pid_file} 2>/dev/null || true")
    pid = pid_res.stdout.strip()

    is_running = False
    if pid:
        check_res = ssh_wpcli.run_ssh_raw(site_config, f"kill -0 {pid} 2>/dev/null && echo 'RUNNING' || echo 'DONE'")
        is_running = "RUNNING" in check_res.stdout

    log_res = ssh_wpcli.run_ssh_raw(site_config, f"tail -n 50 {log_file} 2>/dev/null || true")

    return {
        "site": site,
        "job_id": job_id,
        "pid": pid or None,
        "is_running": is_running,
        "status": "running" if is_running else "completed",
        "recent_logs": log_res.stdout,
    }


def wp_cli_job_cancel(site: str, job_id: str) -> dict:
    """Terminate a background WP-CLI job."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport != "ssh":
        return {"error": "wp_cli_job_cancel is available only on SSH-configured sites"}

    pid_file = f"/tmp/wpguard_job_{job_id}.pid"
    ssh_wpcli.run_ssh_raw(site_config, f"pid=$(cat {pid_file} 2>/dev/null); [ -n \"$pid\" ] && kill -9 $pid || true")

    return {"site": site, "job_id": job_id, "cancelled": True}
