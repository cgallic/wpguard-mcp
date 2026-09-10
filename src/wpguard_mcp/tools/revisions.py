"""Read and restore WordPress-native post revisions."""

from __future__ import annotations

from typing import Any

from ..config import get_site_registry
from ..corrections import assert_corrections_allow, evaluate_corrections
from ..guard import ConflictError, build_change_digest, get_packet_store, get_snapshot_store, require_approved_packet
from ..recon_safety import wrap_untrusted
from ..transports import companion_plugin, ssh_wpcli
from .blocks import _read_post, _revision_ids, _verified_revision
from .pages import _bounded_diff, _page_context, _sha256


def _revision(site_config, post_id: int, revision_id: int) -> dict[str, Any]:
    if site_config.transport == "companion_plugin":
        raw = companion_plugin.call(site_config, "revision_get", {"post_id": post_id, "revision_id": revision_id})
    else:
        raw = ssh_wpcli.run_wp_cli_json(
            site_config,
            [
                "post",
                "get",
                str(revision_id),
                "--fields=ID,post_parent,post_date,post_modified,post_author,post_content",
            ],
        )
    if not isinstance(raw, dict):
        raise ValueError("WordPress returned an invalid revision")
    parent = int(raw.get("post_parent") or raw.get("parent_id") or 0)
    if parent != post_id:
        raise ValueError(f"revision {revision_id} does not belong to post {post_id}")
    content = raw.get("post_content", raw.get("content", ""))
    if not isinstance(content, str):
        content = str(content)
    return {
        "revision_id": int(raw.get("ID") or raw.get("revision_id") or revision_id),
        "post_id": parent,
        "date": raw.get("post_date", raw.get("date", "")),
        "modified": raw.get("post_modified", raw.get("modified", "")),
        "author": raw.get("post_author", raw.get("author", "")),
        "content": content,
        "content_sha256": _sha256(content),
    }


def wp_revision_list(site: str, post_id: int, limit: int = 20) -> dict:
    """List native revisions for a post with complete content hashes."""
    if not isinstance(post_id, int) or isinstance(post_id, bool) or post_id <= 0:
        raise ValueError("post_id must be a positive integer")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    site_config = get_site_registry().get(site)
    if site_config.transport == "companion_plugin":
        response = companion_plugin.call(site_config, "revision_list", {"post_id": post_id, "limit": limit})
        raw = response.get("revisions", []) if isinstance(response, dict) else []
    else:
        raw = (
            ssh_wpcli.run_wp_cli_json(
                site_config,
                [
                    "post",
                    "list",
                    "--post_type=revision",
                    f"--post_parent={post_id}",
                    "--fields=ID,post_parent,post_date,post_modified,post_author",
                    "--orderby=ID",
                    "--order=DESC",
                    f"--posts_per_page={limit}",
                ],
            )
            or []
        )
    revisions = []
    for item in raw[:limit]:
        revision_id = int(item.get("ID", item.get("revision_id")))
        revision = _revision(site_config, post_id, revision_id)
        revisions.append({key: value for key, value in revision.items() if key != "content"})
    return {"site": site, "post_id": post_id, "count": len(revisions), "revisions": revisions}


def wp_revision_get(site: str, post_id: int, revision_id: int) -> dict:
    """Read one native revision, keeping its content inside an untrusted-data envelope."""
    site_config = get_site_registry().get(site)
    revision = _revision(site_config, post_id, revision_id)
    content = revision.pop("content")
    return {
        "site": site,
        "revision": {**revision, "content": wrap_untrusted(content, field=f"revision:{revision_id}:content")},
    }


def wp_revert_to_revision(
    site: str,
    post_id: int,
    revision_id: int,
    apply: bool = False,
    expected_etag: str | None = None,
) -> dict:
    """Preview or restore a post body from a native revision under the normal write guards."""
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in (post_id, revision_id)
    ):
        raise ValueError("post_id and revision_id must be positive integers")
    site_config = get_site_registry().get(site)
    current = _read_post(site_config, post_id)
    revision = _revision(site_config, post_id, revision_id)
    current_content = current["content"]
    proposed_content = revision["content"]
    current_etag = _sha256(current_content)[:16]
    target = f"post:{post_id}:content"
    payload = {"post_id": post_id, "revision_id": revision_id, "revision_content_sha256": revision["content_sha256"]}
    change_digest = build_change_digest(site, "wp_revert_to_revision", target, current_etag, payload)
    corrections = evaluate_corrections(site, target, proposed_content)
    preview = {
        "site": site,
        "dry_run": not apply,
        "applied": False,
        "target": _page_context(current),
        "revision": {key: value for key, value in revision.items() if key != "content"},
        "fields_restored": ["post_content"],
        "etag": current_etag,
        "change_digest": change_digest,
        "diff": _bounded_diff(current_content, proposed_content, 12_000),
        "corrections": corrections,
    }
    if not apply:
        return preview
    if expected_etag is not None and expected_etag != current_etag:
        raise ConflictError("post changed since revert preview", expected_etag=expected_etag, actual_etag=current_etag)
    assert_corrections_allow(corrections)
    packet = require_approved_packet(get_packet_store(), site, target=target, change_digest=change_digest)
    snapshot = get_snapshot_store().record(
        packet_id=packet.id,
        site=site,
        tool="wp_revert_to_revision",
        target=target,
        previous_value=current_content,
        new_value=proposed_content,
        reread=["post_content", post_id],
    )
    previous_revision_ids = _revision_ids(site_config, post_id)
    if site_config.transport == "companion_plugin":
        companion_plugin.call(
            site_config,
            "revision_revert",
            {
                "post_id": post_id,
                "revision_id": revision_id,
                "expected_content_sha256": _sha256(current_content),
            },
        )
    else:
        ssh_wpcli.run_wp_cli(site_config, ["post", "update", str(post_id), f"--post_content={proposed_content}"])
    resulting_revision = _verified_revision(
        site_config, post_id, revision["content_sha256"], exclude_revision_ids=previous_revision_ids
    )
    get_packet_store().log(
        packet.id,
        f"applied wp_revert_to_revision(post {post_id}, revision {revision_id}) -- "
        f"snapshot {snapshot.id}; resulting revision {resulting_revision.get('revision_id')}",
    )
    return {
        **preview,
        "dry_run": False,
        "applied": True,
        "packet_id": packet.id,
        "snapshot_id": snapshot.id,
        "resulting_revision": resulting_revision,
    }


GUARDED_TOOLS = {"wp_revert_to_revision": wp_revert_to_revision}
