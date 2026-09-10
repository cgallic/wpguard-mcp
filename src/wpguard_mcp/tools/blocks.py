"""Gutenberg Block Editor parsing, composition, validation, and post creation."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from ..config import get_site_registry
from ..corrections import assert_corrections_allow, evaluate_corrections
from ..guard import (
    ConflictError,
    build_change_digest,
    get_packet_store,
    get_snapshot_store,
    require_approved_packet,
)
from ..transports import companion_plugin, ssh_wpcli
from .pages import _bounded_diff, _page_context, _sha256


def _read_post(site_config, post_id: int) -> dict:
    if site_config.transport == "companion_plugin":
        raw = companion_plugin.call(site_config, "post_content_get", {"post_id": post_id})
    else:
        raw = ssh_wpcli.run_wp_cli_json(
            site_config,
            [
                "post",
                "get",
                str(post_id),
                "--fields=ID,post_type,post_title,post_name,post_status,post_modified,post_date,guid,post_content",
            ],
        )
    if not isinstance(raw, dict):
        raise ValueError("WordPress returned an invalid post")
    content = raw.get("post_content", raw.get("content", ""))
    return {
        "id": int(raw.get("ID") or raw.get("id") or post_id),
        "post_type": raw.get("post_type", ""),
        "title": raw.get("post_title", raw.get("title", "")),
        "slug": raw.get("post_name", raw.get("slug", "")),
        "status": raw.get("post_status", raw.get("status", "")),
        "modified": raw.get("post_modified", raw.get("modified", "")),
        "date": raw.get("post_date", raw.get("date", "")),
        "link": raw.get("guid", raw.get("url", raw.get("link", ""))),
        "content": content if isinstance(content, str) else str(content),
    }


def wp_block_parse(site: str, content: str) -> dict:
    """Parse raw HTML / Gutenberg content into structured Block AST."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        php = f"echo json_encode(parse_blocks({repr(content)}));"
        res = ssh_wpcli.run_wp_cli(site_config, ["eval", php])
        import json

        return {"site": site, "blocks": json.loads(res.stdout.strip())}
    else:
        res = companion_plugin.call(site_config, "block_parse", {"content": content})
        return {"site": site, "blocks": res.get("blocks") if isinstance(res, dict) else None}


def wp_block_compose(site: str, blocks: list[dict[str, Any]]) -> dict:
    """Serialize structured Block AST into valid WordPress block markup."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        import json

        php = f"$b = json_decode({repr(json.dumps(blocks))}, true); echo serialize_blocks($b);"
        res = ssh_wpcli.run_wp_cli(site_config, ["eval", php])
        return {"site": site, "markup": res.stdout}
    else:
        res = companion_plugin.call(site_config, "block_compose", {"blocks": blocks})
        return {"site": site, "markup": res.get("markup") if isinstance(res, dict) else None}


def wp_block_validate(site: str, block_markup: str) -> dict:
    """Validate block markup syntax and check for unclosed delimiters."""
    open_count = block_markup.count("<!-- wp:")
    close_count = block_markup.count("/-->") + block_markup.count("<!-- /wp:")
    valid = (open_count > 0 and open_count <= close_count) or (open_count == 0)

    return {
        "site": site,
        "valid": valid,
        "open_block_tags": open_count,
        "close_block_tags": close_count,
    }


def wp_post_create(
    site: str,
    title: str,
    content: str = "",
    post_type: str = "post",
    status: str = "draft",
    meta: dict[str, Any] | None = None,
    apply: bool = False,
) -> dict:
    """Create a new post, page, or CPT with Gutenberg blocks or raw content."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if not apply:
        return {
            "site": site,
            "dry_run": True,
            "applied": False,
            "title": title,
            "post_type": post_type,
            "status": status,
            "meta": meta or {},
            "content_preview": content[:150] + ("..." if len(content) > 150 else ""),
        }

    packet = require_approved_packet(get_packet_store(), site)

    if site_config.transport == "ssh":
        import json

        php_code = (
            f"$data = ['post_title' => {repr(title)}, 'post_content' => {repr(content)}, "
            f"'post_type' => {repr(post_type)}, 'post_status' => {repr(status)}, "
            f"'meta_input' => json_decode({repr(json.dumps(meta or {}))}, true)]; "
            f"$id = wp_insert_post($data, true); "
            f"if (is_wp_error($id)) {{ echo json_encode(['error' => $id->get_error_message()]); }} "
            f"else {{ echo json_encode(['post_id' => $id, 'url' => get_permalink($id)]); }}"
        )
        res = ssh_wpcli.run_wp_cli(site_config, ["eval", php_code])
        result = json.loads(res.stdout.strip())
    else:
        result = companion_plugin.call(
            site_config,
            "post_create",
            {
                "title": title,
                "content": content,
                "post_type": post_type,
                "status": status,
                "meta": meta or {},
                "apply": True,
            },
        )

    get_packet_store().log(packet.id, f"applied wp_post_create('{title}', {post_type})")
    return {
        "site": site,
        "dry_run": False,
        "applied": True,
        "packet_id": packet.id,
        "result": result,
    }


def _walk_blocks(blocks: list[dict[str, Any]], path: tuple[int, ...] = ()):
    for index, block in enumerate(blocks):
        block_path = (*path, index)
        yield block_path, block
        inner = block.get("innerBlocks", [])
        if isinstance(inner, list):
            yield from _walk_blocks(inner, block_path)


def _select_block(blocks: list[dict[str, Any]], selector: dict[str, Any]) -> tuple[tuple[int, ...], dict]:
    if not isinstance(selector, dict):
        raise ValueError("selector must be an object")
    allowed = {"path", "block_name", "client_id", "occurrence"}
    if not selector or set(selector) - allowed:
        raise ValueError("selector supports path, block_name, client_id, and occurrence")
    walked = list(_walk_blocks(blocks))
    if "path" in selector:
        raw_path = selector["path"]
        if (
            not isinstance(raw_path, list)
            or not raw_path
            or any(not isinstance(index, int) or isinstance(index, bool) or index < 0 for index in raw_path)
        ):
            raise ValueError("selector.path must be a nonempty list of nonnegative integers")
        matches = [(path, block) for path, block in walked if path == tuple(raw_path)]
    else:
        if not any(selector.get(key) for key in ("block_name", "client_id")):
            raise ValueError("selector needs path, block_name, or client_id")
        matches = []
        for path, block in walked:
            attrs = block.get("attrs") if isinstance(block.get("attrs"), dict) else {}
            client_id = attrs.get("clientId", attrs.get("client_id"))
            if selector.get("block_name") and block.get("blockName") != selector["block_name"]:
                continue
            if selector.get("client_id") and client_id != selector["client_id"]:
                continue
            matches.append((path, block))
        occurrence = selector.get("occurrence")
        if occurrence is not None:
            if not isinstance(occurrence, int) or isinstance(occurrence, bool) or occurrence < 0:
                raise ValueError("selector.occurrence must be a nonnegative integer")
            matches = matches[occurrence : occurrence + 1]
    if not matches:
        raise ValueError("selector did not match a block")
    if len(matches) > 1:
        raise ValueError("selector matched multiple blocks; add occurrence or use an exact path")
    return matches[0]


def _parse_blocks(site_config, content: str) -> list[dict[str, Any]]:
    if site_config.transport == "ssh":
        php = f"echo wp_json_encode(parse_blocks({repr(content)}));"
        raw = ssh_wpcli.run_wp_cli(site_config, ["eval", php]).stdout.strip()
        parsed = json.loads(raw)
    else:
        response = companion_plugin.call(site_config, "block_parse", {"content": content})
        parsed = response.get("blocks") if isinstance(response, dict) else None
    if not isinstance(parsed, list):
        raise ValueError("WordPress returned an invalid block tree")
    return parsed


def _serialize_blocks(site_config, blocks: list[dict[str, Any]]) -> str:
    result: Any
    if site_config.transport == "ssh":
        encoded = json.dumps(blocks, ensure_ascii=False, separators=(",", ":"))
        php = f"$b=json_decode({repr(encoded)},true); echo serialize_blocks($b);"
        result = ssh_wpcli.run_wp_cli(site_config, ["eval", php]).stdout
    else:
        response = companion_plugin.call(site_config, "block_compose", {"blocks": blocks})
        result = response.get("markup") if isinstance(response, dict) else None
    if not isinstance(result, str):
        raise ValueError("WordPress returned invalid serialized block markup")
    return result


def _revision_ids(site_config, post_id: int) -> set[int]:
    if site_config.transport == "companion_plugin":
        result = companion_plugin.call(site_config, "revision_list", {"post_id": post_id, "limit": 100})
        rows = result.get("revisions", []) if isinstance(result, dict) else []
    else:
        raw_rows = ssh_wpcli.run_wp_cli_json(
            site_config,
            [
                "post",
                "list",
                "--post_type=revision",
                f"--post_parent={post_id}",
                "--fields=ID",
                "--orderby=ID",
                "--order=DESC",
                "--posts_per_page=100",
            ],
        )
        rows = raw_rows if isinstance(raw_rows, list) else []
    return {int(row.get("ID", row.get("revision_id"))) for row in rows}


def _verified_revision(
    site_config, post_id: int, content_sha256: str, exclude_revision_ids: set[int] | None = None
) -> dict:
    """Find a native revision whose complete content hash matches the write."""
    excluded = exclude_revision_ids or set()
    if site_config.transport == "companion_plugin":
        result = companion_plugin.call(
            site_config,
            "revision_find",
            {"post_id": post_id, "content_sha256": content_sha256, "exclude_revision_ids": sorted(excluded)},
        )
        if isinstance(result, dict) and result.get("revision_id"):
            return {
                "supported": True,
                "revision_id": int(result["revision_id"]),
                "content_sha256": content_sha256,
                "verified": True,
            }
        return {
            "supported": False,
            "revision_id": None,
            "content_sha256": content_sha256,
            "verified": False,
            "reason": "No matching native revision was returned",
        }
    raw_revisions = ssh_wpcli.run_wp_cli_json(
        site_config,
        [
            "post",
            "list",
            "--post_type=revision",
            f"--post_parent={post_id}",
            "--fields=ID",
            "--orderby=ID",
            "--order=DESC",
            "--posts_per_page=20",
        ],
    )
    revisions = raw_revisions if isinstance(raw_revisions, list) else []
    for revision in revisions:
        revision_id = int(revision["ID"])
        if revision_id in excluded:
            continue
        content = ssh_wpcli.run_wp_cli(site_config, ["post", "get", str(revision_id), "--field=content"]).stdout.rstrip(
            "\n"
        )
        if _sha256(content) == content_sha256:
            return {"supported": True, "revision_id": revision_id, "content_sha256": content_sha256, "verified": True}
    return {
        "supported": False,
        "revision_id": None,
        "content_sha256": content_sha256,
        "verified": False,
        "reason": "WordPress did not create a matching native revision",
    }


def wp_mutate_block(
    site: str,
    post_id: int,
    selector: dict[str, Any],
    attrs_patch: dict[str, Any] | None = None,
    inner_html: str | None = None,
    apply: bool = False,
    expected_etag: str | None = None,
) -> dict:
    """Structurally mutate one Gutenberg block selected by path, type, or stored client ID."""
    if not isinstance(post_id, int) or isinstance(post_id, bool) or post_id <= 0:
        raise ValueError("post_id must be a positive integer")
    if attrs_patch is None and inner_html is None:
        raise ValueError("provide attrs_patch or inner_html")
    if attrs_patch is not None and not isinstance(attrs_patch, dict):
        raise ValueError("attrs_patch must be an object")
    if inner_html is not None and not isinstance(inner_html, str):
        raise ValueError("inner_html must be a string")
    site_config = get_site_registry().get(site)
    page = _read_post(site_config, post_id)
    current_content = page["content"]
    blocks = _parse_blocks(site_config, current_content)
    proposed_blocks = deepcopy(blocks)
    path, block = _select_block(proposed_blocks, selector)
    original_block_name = block.get("blockName")
    if attrs_patch is not None:
        attrs = block.get("attrs")
        if not isinstance(attrs, dict):
            attrs = {}
            block["attrs"] = attrs
        attrs.update(attrs_patch)
    if inner_html is not None:
        if block.get("innerBlocks"):
            raise ValueError("inner_html cannot replace a block that contains nested blocks")
        block["innerHTML"] = inner_html
        block["innerContent"] = [inner_html]
    proposed_content = _serialize_blocks(site_config, proposed_blocks)
    current_etag = _sha256(current_content)[:16]
    target = f"post:{post_id}:content"
    payload = {
        "post_id": post_id,
        "selector": selector,
        "attrs_patch": attrs_patch,
        "inner_html_sha256": _sha256(inner_html) if inner_html is not None else None,
        "proposed_content_sha256": _sha256(proposed_content),
    }
    change_digest = build_change_digest(site, "wp_mutate_block", target, current_etag, payload)
    correction_report = evaluate_corrections(site, target, proposed_content)
    preview = {
        "site": site,
        "dry_run": not apply,
        "applied": False,
        "target": _page_context(page),
        "block": {"path": list(path), "block_name": original_block_name},
        "proposed": {"content_sha256": _sha256(proposed_content), "content_length": len(proposed_content)},
        "etag": current_etag,
        "change_digest": change_digest,
        "diff": _bounded_diff(current_content, proposed_content, 12_000),
        "corrections": correction_report,
    }
    if not apply:
        return preview
    if expected_etag is not None and expected_etag != current_etag:
        raise ConflictError(
            "post changed since preview: refusing block mutation", expected_etag=expected_etag, actual_etag=current_etag
        )
    assert_corrections_allow(correction_report)
    packet = require_approved_packet(get_packet_store(), site, target=target, change_digest=change_digest)
    snapshot = get_snapshot_store().record(
        packet_id=packet.id,
        site=site,
        tool="wp_mutate_block",
        target=target,
        previous_value=current_content,
        new_value=proposed_content,
        reread=["post_content", post_id],
    )
    previous_revision_ids = _revision_ids(site_config, post_id)
    if site_config.transport == "ssh":
        ssh_wpcli.run_wp_cli(site_config, ["post", "update", str(post_id), f"--post_content={proposed_content}"])
    else:
        companion_plugin.call(
            site_config,
            "post_content_replace",
            {
                "post_id": post_id,
                "new_content": proposed_content,
                "expected_content_sha256": _sha256(current_content),
            },
        )
    native_revision = _verified_revision(
        site_config, post_id, _sha256(proposed_content), exclude_revision_ids=previous_revision_ids
    )
    get_packet_store().log(
        packet.id,
        f"applied wp_mutate_block(post {post_id}, path {list(path)}) -- "
        f"snapshot {snapshot.id}; native revision {native_revision.get('revision_id')}",
    )
    return {
        **preview,
        "dry_run": False,
        "applied": True,
        "packet_id": packet.id,
        "snapshot_id": snapshot.id,
        "native_revision": native_revision,
    }


GUARDED_TOOLS = {"wp_mutate_block": wp_mutate_block}
