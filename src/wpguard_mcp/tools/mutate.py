"""Tier 2 (guarded named verbs) and Tier 3 (guarded raw escape hatch) tools.

Every tool here shares one shape:

- Dry-run by default (`apply=False`): read the current value, compute what
  *would* change, and return a preview -- including an `etag` fingerprint of
  the value it read. Never touches the live site.
- `apply=True`: requires an *approved*, still-open change packet for `site`
  (see guard.py) unless WPGUARD_BYPASS_GUARD=1 is set. Every guarded tool
  funnels through the one shared gate `require_approved_packet` -- none has its
  own inline check -- so the gate cannot be skipped by a new tool. Captures a
  "previous value" snapshot immediately before writing, so the write is always
  reversible in principle. Then performs the write and logs it onto the packet.

Optimistic concurrency (issue #6): the caller may pass the `etag` it got from a
dry-run back on the apply call as `expected_etag`. If the live value changed in
between (its etag no longer matches), the apply is refused with a ConflictError
rather than blindly overwriting someone else's change.

wp_cache_bust is the one Tier 2 exception: it has no persistent content
effect, so it is not guarded and has no apply flag -- it always runs.
"""
from __future__ import annotations

import hashlib

from ..config import get_site_registry
from ..guard import (
    ConflictError,
    build_change_digest,
    get_packet_store,
    get_snapshot_store,
    require_approved_packet,
)
from ..notify import emit_event
from ..transports import companion_plugin, ssh_wpcli


def _etag(value) -> str:
    """A short, stable fingerprint of a value, used for optimistic concurrency."""
    text = "" if value is None else str(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _check_etag(expected_etag: str | None, current_value) -> str:
    """Return the current value's etag, raising ConflictError if it doesn't match
    a non-None `expected_etag`.
    """
    actual = _etag(current_value)
    if expected_etag is not None and expected_etag != actual:
        raise ConflictError(
            "value changed since dry-run: refusing to overwrite. Re-run the dry-run to "
            f"preview against current state (expected etag {expected_etag}, live etag {actual}).",
            expected_etag=expected_etag,
            actual_etag=actual,
        )
    return actual


def _change_digest(site: str, verb: str, target: str, current_etag: str | None, payload: dict) -> str:
    return build_change_digest(
        site=site,
        verb=verb,
        target=target,
        current_etag=current_etag,
        payload=payload,
    )


def wp_mutate_option(
    site: str,
    option_name: str,
    new_value: str,
    apply: bool = False,
    expected_etag: str | None = None,
) -> dict:
    """Update a WP option. Tier 2 -- dry-run unless apply=True, requires an
    approved change packet for `site` to actually write.

    Dry-run returns an `etag` fingerprint of the current value; pass it back as
    `expected_etag` on the apply call to refuse the write if the value changed
    in between (optimistic concurrency).
    """
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        previous_value = ssh_wpcli.run_wp_cli(site_config, ["option", "get", option_name]).stdout.strip()
    else:
        previous_value = companion_plugin.call(site_config, "get_option", {"option_name": option_name})

    target = f"option:{option_name}"
    payload = {"option_name": option_name, "new_value": new_value}
    current_etag = _etag(previous_value)
    change_digest = _change_digest(site, "wp_mutate_option", target, current_etag, payload)
    if not apply:
        return {
            "site": site,
            "dry_run": True,
            "applied": False,
            "option_name": option_name,
            "previous_value": previous_value,
            "proposed_value": new_value,
            "etag": current_etag,
            "change_digest": change_digest,
        }

    _check_etag(expected_etag, previous_value)
    packet = require_approved_packet(
        get_packet_store(), site, target=target, change_digest=change_digest
    )
    snapshot = get_snapshot_store().record(
        packet_id=packet.id,
        site=site,
        tool="wp_mutate_option",
        target=target,
        previous_value=previous_value,
        new_value=new_value,
        reread=["option", option_name],
    )

    if site_config.transport == "ssh":
        ssh_wpcli.run_wp_cli(site_config, ["option", "update", option_name, new_value])
    else:
        companion_plugin.call(site_config, "update_option", {"option_name": option_name, "new_value": new_value})

    get_packet_store().log(packet.id, f"applied wp_mutate_option({option_name}) -- snapshot {snapshot.id}")
    return {
        "site": site,
        "dry_run": False,
        "applied": True,
        "option_name": option_name,
        "previous_value": previous_value,
        "new_value": new_value,
        "packet_id": packet.id,
        "snapshot_id": snapshot.id,
    }


def wp_mutate_post_meta(
    site: str,
    post_id: int,
    meta_key: str,
    new_value: str,
    apply: bool = False,
    expected_etag: str | None = None,
) -> dict:
    """Update a single post's meta value. Tier 2 -- dry-run unless apply=True,
    requires an approved change packet for `site` to actually write.
    """
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        previous_value = ssh_wpcli.run_wp_cli(
            site_config, ["post", "meta", "get", str(post_id), meta_key]
        ).stdout.strip()
    else:
        previous_value = companion_plugin.call(
            site_config, "get_post_meta", {"post_id": post_id, "meta_key": meta_key}
        )

    target = f"post:{post_id}:{meta_key}"
    payload = {"post_id": post_id, "meta_key": meta_key, "new_value": new_value}
    current_etag = _etag(previous_value)
    change_digest = _change_digest(site, "wp_mutate_post_meta", target, current_etag, payload)
    if not apply:
        return {
            "site": site,
            "dry_run": True,
            "applied": False,
            "post_id": post_id,
            "meta_key": meta_key,
            "previous_value": previous_value,
            "proposed_value": new_value,
            "etag": current_etag,
            "change_digest": change_digest,
        }

    _check_etag(expected_etag, previous_value)
    packet = require_approved_packet(
        get_packet_store(), site, target=target, change_digest=change_digest
    )
    snapshot = get_snapshot_store().record(
        packet_id=packet.id,
        site=site,
        tool="wp_mutate_post_meta",
        target=target,
        previous_value=previous_value,
        new_value=new_value,
        reread=["post_meta", post_id, meta_key],
    )

    if site_config.transport == "ssh":
        ssh_wpcli.run_wp_cli(site_config, ["post", "meta", "update", str(post_id), meta_key, new_value])
    else:
        companion_plugin.call(
            site_config,
            "update_post_meta",
            {"post_id": post_id, "meta_key": meta_key, "new_value": new_value},
        )

    get_packet_store().log(
        packet.id, f"applied wp_mutate_post_meta(post {post_id}, {meta_key}) -- snapshot {snapshot.id}"
    )
    return {
        "site": site,
        "dry_run": False,
        "applied": True,
        "post_id": post_id,
        "meta_key": meta_key,
        "previous_value": previous_value,
        "new_value": new_value,
        "packet_id": packet.id,
        "snapshot_id": snapshot.id,
    }


def wp_mutate_post_content(
    site: str,
    post_id: int,
    search: str,
    replace: str,
    apply: bool = False,
    expected_etag: str | None = None,
) -> dict:
    """Search/replace within a single post's content. Tier 2 -- dry-run unless
    apply=True, requires an approved change packet for `site` to actually write.

    Dry-run returns the number of matches found and an `etag` of the current
    content, and does not touch the post.
    """
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        current_content = ssh_wpcli.run_wp_cli(
            site_config, ["post", "get", str(post_id), "--field=content"]
        ).stdout.rstrip("\n")
        match_count = current_content.count(search)
        proposed_content = current_content.replace(search, replace)

        target = f"post:{post_id}:content"
        payload = {"post_id": post_id, "search": search, "replace": replace}
        current_etag = _etag(current_content)
        change_digest = _change_digest(
            site, "wp_mutate_post_content", target, current_etag, payload
        )
        if not apply:
            return {
                "site": site,
                "dry_run": True,
                "applied": False,
                "post_id": post_id,
                "search": search,
                "replace": replace,
                "match_count": match_count,
                "etag": current_etag,
                "change_digest": change_digest,
            }

        _check_etag(expected_etag, current_content)
        packet = require_approved_packet(
            get_packet_store(), site, target=target, change_digest=change_digest
        )
        snapshot = get_snapshot_store().record(
            packet_id=packet.id,
            site=site,
            tool="wp_mutate_post_content",
            target=target,
            previous_value=current_content,
            new_value=proposed_content,
            reread=["post_content", post_id],
        )
        ssh_wpcli.run_wp_cli(site_config, ["post", "update", str(post_id), f"--post_content={proposed_content}"])
        get_packet_store().log(
            packet.id,
            f"applied wp_mutate_post_content(post {post_id}, {match_count} matches) -- snapshot {snapshot.id}",
        )
        return {
            "site": site,
            "dry_run": False,
            "applied": True,
            "post_id": post_id,
            "match_count": match_count,
            "packet_id": packet.id,
            "snapshot_id": snapshot.id,
        }

    # companion_plugin transport: the plugin does the read+count+(optional)write
    # server-side so we don't need a separate get-content command in its
    # whitelist. Passing apply=False makes it preview only.
    preview = companion_plugin.call(
        site_config,
        "search_replace_post_content",
        {"post_id": post_id, "search": search, "replace": replace, "apply": False},
    )
    match_count = (preview or {}).get("match_count", 0)
    previous_content = (preview or {}).get("previous_content")

    target = f"post:{post_id}:content"
    payload = {"post_id": post_id, "search": search, "replace": replace}
    current_etag = _etag(previous_content)
    change_digest = _change_digest(
        site, "wp_mutate_post_content", target, current_etag, payload
    )
    if not apply:
        return {
            "site": site,
            "dry_run": True,
            "applied": False,
            "post_id": post_id,
            "search": search,
            "replace": replace,
            "match_count": match_count,
            "etag": current_etag,
            "change_digest": change_digest,
        }

    _check_etag(expected_etag, previous_content)
    packet = require_approved_packet(
        get_packet_store(), site, target=target, change_digest=change_digest
    )
    companion_new_content = (
        previous_content.replace(search, replace) if isinstance(previous_content, str) else None
    )
    snapshot = get_snapshot_store().record(
        packet_id=packet.id,
        site=site,
        tool="wp_mutate_post_content",
        target=target,
        previous_value=previous_content,
        new_value=companion_new_content,
        reread=["post_content", post_id],
    )
    result = companion_plugin.call(
        site_config,
        "search_replace_post_content",
        {"post_id": post_id, "search": search, "replace": replace, "apply": True},
    )
    get_packet_store().log(
        packet.id, f"applied wp_mutate_post_content(post {post_id}, {match_count} matches) -- snapshot {snapshot.id}"
    )
    return {
        "site": site,
        "dry_run": False,
        "applied": True,
        "post_id": post_id,
        "match_count": (result or {}).get("match_count", match_count),
        "packet_id": packet.id,
        "snapshot_id": snapshot.id,
    }


def wp_cache_bust(site: str) -> dict:
    """Flush the site's object/page cache. Not guarded -- no content change,
    nothing to snapshot, no packet required. Runs immediately.
    """
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        detail = ssh_wpcli.run_wp_cli(site_config, ["cache", "flush"]).stdout.strip()
    else:
        detail = companion_plugin.call(site_config, "cache_flush")

    return {"site": site, "cache_flushed": True, "detail": detail}


def wp_eval(site: str, php_code: str, apply: bool = False) -> dict:
    """Tier 3 escape hatch: run arbitrary PHP via `wp eval` on `site`.

    SSH-only -- the companion plugin has no eval capability by design.
    Dry-run by default; apply=True requires an approved change packet for
    `site`, same as every Tier 2 tool. There is no generic way to snapshot
    "previous state" for arbitrary code, so the snapshot recorded here has
    previous_value=None; treat wp_eval changes as manually-verified-only.
    """
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport != "ssh":
        raise ValueError(
            f"wp_eval is SSH-only (Tier 3); site '{site}' is registered via companion_plugin, "
            f"which never exposes raw PHP eval. Register an ssh-transport site to use wp_eval."
        )

    target = "raw_php_eval"
    payload = {"php_code": php_code}
    change_digest = _change_digest(site, "wp_eval", target, None, payload)
    if not apply:
        return {
            "site": site,
            "dry_run": True,
            "applied": False,
            "php_code": php_code,
            "change_digest": change_digest,
            "note": "not executed; call again with apply=True and an approved change packet to run",
        }

    packet = require_approved_packet(
        get_packet_store(), site, target=target, change_digest=change_digest
    )
    snapshot = get_snapshot_store().record(
        packet_id=packet.id, site=site, tool="wp_eval", target=target, previous_value=None
    )
    result = ssh_wpcli.run_eval(site_config, php_code)
    get_packet_store().log(
        packet.id,
        f"applied wp_eval (raw PHP, Tier 3) -- snapshot {snapshot.id} recorded with no previous-value "
        f"capture; verify manually",
    )
    emit_event("tier3_eval_fired", {**packet.to_dict(), "php_code_len": len(php_code)})
    return {
        "site": site,
        "dry_run": False,
        "applied": True,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "packet_id": packet.id,
        "snapshot_id": snapshot.id,
    }


# The canonical registry of guarded (Tier 2/3) mutating tools. server.py
# registers exactly these as guarded tools, and tests/test_guard_enumeration.py
# asserts every one of them funnels an apply=True call through
# require_approved_packet. Keeping the list here (rather than re-deriving it in
# two places) is what makes "you cannot add a guarded tool that skips the gate"
# a checkable property.
GUARDED_TOOLS = {
    "wp_mutate_option": wp_mutate_option,
    "wp_mutate_post_meta": wp_mutate_post_meta,
    "wp_mutate_post_content": wp_mutate_post_content,
    "wp_eval": wp_eval,
}
