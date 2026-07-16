"""Packet lifecycle tools (packet_open / packet_approve / packet_log /
packet_close / packet_list) and site_register -- the tools that set up and
account for guarded work, as opposed to the recon/mutate tools that do the
guarded work itself.

The lifecycle is deliberately two-step: `packet_open` *proposes* a change and
`packet_approve` *authorizes* it. Only an approved packet satisfies the guard
for an `apply=True` write (see guard.require_approved_packet). Splitting propose
from approve is what lets the actor asking for a change be different from the
actor signing off on it.
"""
from __future__ import annotations

import time

from ..config import SiteConfig, get_site_registry
from ..guard import get_packet_store, get_snapshot_store
from ..notify import emit_event
from ..transports import companion_plugin, ssh_wpcli


def packet_open(site: str, summary: str, risk: str = "low", target: str = "*") -> dict:
    """Open (propose) a change packet for `site`. Required before any apply=True
    mutation on that site -- but note the packet must also be *approved*
    (packet_approve) before the guard will let a write through.

    `target` names the specific resource this packet intends to change (e.g.
    "option:blogname" or "post:12:content"), defaulting to "*" (whole site).
    While the packet is open it holds a lock on that target: a second
    packet_open on an overlapping target fails fast with a clear error instead
    of silently racing. Locks auto-expire after WPGUARD_LOCK_TTL_SECONDS.

    `risk` is a free-text label (e.g. "low", "medium", "high") -- wpguard
    doesn't enforce a fixed enum, but the README recommends staying consistent
    so packet history stays scannable.
    """
    store = get_packet_store()
    packet = store.open_packet(site=site, summary=summary, risk=risk, target=target)
    emit_event("packet_proposed", packet.to_dict())
    return packet.to_dict()


def packet_approve(packet_id: str, approver: str) -> dict:
    """Authorize a proposed packet so apply=True writes against its site can run.

    `approver` is a free-text identifier of who/what approved the change (a
    username, an agent id, "policy:auto"). Recorded on the packet. Approving an
    already-approved packet is a no-op; approving a closed packet is an error.
    """
    store = get_packet_store()
    packet = store.approve_packet(packet_id, approver=approver)
    emit_event("packet_approved", packet.to_dict())
    return packet.to_dict()


def packet_log(packet_id: str, message: str) -> dict:
    """Append a log line to an open packet -- e.g. "dry-run previewed", "applied,
    old value captured", "verified via wp_recon". Fails if the packet is closed.
    """
    store = get_packet_store()
    packet = store.log(packet_id, message)
    return packet.to_dict()


def packet_close(packet_id: str, outcome: str = "", durable_check_delay_seconds: int | None = None) -> dict:
    """Close a packet once the change has been applied and verified.

    `outcome` is a free-text summary of the result, e.g. "verified, homepage
    loads, option confirmed via wp_get_option".

    Optional durable re-verify (issue #2): if `durable_check_delay_seconds` is
    provided, wait that many seconds and then re-read every value this packet
    mutated, comparing it to what was written. This catches the failure mode
    where a write looks successful immediately but doesn't durably stick (a
    cache layer serving stale content, a plugin re-writing the field on its
    next cron tick, async replication that hasn't landed). If any mutated value
    has drifted from what was written, the packet is closed as
    `outcome="verify_failed: ..."` with the drift attached, instead of as the
    caller's success outcome. Opt-in because it adds real latency.
    """
    store = get_packet_store()

    durable = None
    if durable_check_delay_seconds is not None:
        durable = _run_durable_check(packet_id, max(0, durable_check_delay_seconds))
        if not durable["durable"]:
            drift_summary = "; ".join(
                f"{d['target']} drifted" for d in durable["checks"] if not d["ok"]
            )
            outcome = f"verify_failed: {drift_summary} (see durable_check)".strip()

    packet = store.close_packet(packet_id, outcome=outcome)
    result = packet.to_dict()
    if durable is not None:
        result["durable_check"] = durable
    emit_event("packet_verify_failed" if durable and not durable["durable"] else "packet_closed", result)
    return result


def _run_durable_check(packet_id: str, delay_seconds: int) -> dict:
    """Sleep, then re-read each snapshot's mutated value and compare to what was
    written. Returns a structured report; never raises on a single failed read.
    """
    snapshots = get_snapshot_store().list_for_packet(packet_id)
    if delay_seconds > 0:
        time.sleep(delay_seconds)

    registry = get_site_registry()
    checks: list[dict] = []
    for snap in snapshots:
        if snap.reread is None or snap.new_value is None:
            checks.append(
                {"target": snap.target, "ok": True, "skipped": True, "reason": "no re-read available for this tool"}
            )
            continue
        try:
            site_config = registry.get(snap.site)
            current = _reread_current_value(site_config, snap.reread)
        except Exception as exc:  # best-effort: a failed re-read is reported, not fatal
            checks.append({"target": snap.target, "ok": False, "error": str(exc)})
            continue
        ok = str(current) == str(snap.new_value)
        checks.append(
            {
                "target": snap.target,
                "ok": ok,
                "written_value": snap.new_value,
                "current_value": current,
            }
        )

    durable = all(c["ok"] for c in checks)
    return {"durable": durable, "delay_seconds": delay_seconds, "checks": checks}


def _reread_current_value(site_config: SiteConfig, spec: list):
    """Re-read a mutated value using a snapshot `reread` spec (see guard.Snapshot)."""
    kind = spec[0]
    if kind == "option":
        option_name = spec[1]
        if site_config.transport == "ssh":
            return ssh_wpcli.run_wp_cli(site_config, ["option", "get", option_name]).stdout.strip()
        return companion_plugin.call(site_config, "get_option", {"option_name": option_name})
    if kind == "post_meta":
        post_id, meta_key = spec[1], spec[2]
        if site_config.transport == "ssh":
            return ssh_wpcli.run_wp_cli(
                site_config, ["post", "meta", "get", str(post_id), meta_key]
            ).stdout.strip()
        return companion_plugin.call(site_config, "get_post_meta", {"post_id": post_id, "meta_key": meta_key})
    if kind == "post_content":
        post_id = spec[1]
        if site_config.transport == "ssh":
            return ssh_wpcli.run_wp_cli(
                site_config, ["post", "get", str(post_id), "--field=content"]
            ).stdout.rstrip("\n")
        # The companion plugin has no read-only content command; skip durable
        # content checks on plugin-transport sites rather than adding one.
        raise NotImplementedError("post_content durable re-read is SSH-only")
    raise ValueError(f"unknown re-read spec kind '{kind}'")


def packet_list(site: str | None = None, open_only: bool = False, status: str | None = None) -> list[dict]:
    """List packets, optionally filtered to one site, only-open packets, and/or a
    specific status ("proposed" | "approved" | "closed").

    A cheap coordination primitive for multi-agent setups: call
    packet_list(status="approved") or packet_list(open_only=True) to see what's
    already in flight before proposing new work against the same target.
    """
    store = get_packet_store()
    return [p.to_dict() for p in store.list_packets(site=site, open_only=open_only, status=status)]


def site_register(
    name: str,
    transport: str,
    ssh_host: str | None = None,
    ssh_user: str | None = None,
    ssh_port: int = 22,
    ssh_key_path: str | None = None,
    wp_path: str | None = None,
    layout: str = "classic",
    plugin_url: str | None = None,
    plugin_api_key_env: str | None = None,
    notes: str = "",
    overwrite: bool = False,
) -> dict:
    """Register a site's connection info into the local site registry.

    For transport="ssh": provide ssh_host (required), ssh_user, ssh_port,
    ssh_key_path, wp_path (the --path wp-cli needs if WP isn't at the SSH
    login's default directory), and `layout` -- "classic" for a standard
    WordPress docroot, or "bedrock" for a Bedrock/Composer install (docroot
    under web/, config split out of wp-config.php). See config.SiteConfig for
    how `layout` resolves the wp-cli working directory.

    For transport="companion_plugin": provide plugin_url (the site's
    /wp-json/wpguard/v1/exec URL) and plugin_api_key_env (the NAME of an
    environment variable on this machine that holds the plugin's API key --
    never pass the key itself as a tool argument).

    No credentials are ever written to the registry file itself.
    """
    site = SiteConfig(
        name=name,
        transport=transport,
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_key_path=ssh_key_path,
        wp_path=wp_path,
        layout=layout,
        plugin_url=plugin_url,
        plugin_api_key_env=plugin_api_key_env,
        notes=notes,
    )
    registry = get_site_registry()
    registered = registry.register(site, overwrite=overwrite)
    return registered.to_dict()
