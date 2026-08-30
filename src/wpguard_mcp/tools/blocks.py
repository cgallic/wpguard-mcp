"""Gutenberg Block Editor parsing, composition, validation, and post creation."""
from __future__ import annotations

from typing import Any

from ..config import get_site_registry
from ..guard import get_packet_store, require_approved_packet
from ..transports import companion_plugin, ssh_wpcli


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
        return {"site": site, "blocks": (res or {}).get("blocks")}


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
        return {"site": site, "markup": (res or {}).get("markup")}


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
