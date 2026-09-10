"""Outcome-oriented WordPress page reads, comparisons, and guarded replacement."""
from __future__ import annotations

import difflib
import hashlib
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
from ..recon_safety import wrap_untrusted
from ..transports import companion_plugin, ssh_wpcli

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100
DEFAULT_DIFF_MAX_CHARS = 12_000
MAX_DIFF_MAX_CHARS = 50_000


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _etag(value: str) -> str:
    return _sha256(value)[:16]


def _page_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("page id must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("page id must be a positive integer") from exc
    if result <= 0:
        raise ValueError("page id must be a positive integer")
    return result


def _normalize_page(raw: Any, *, include_content: bool = True) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("WordPress returned an invalid page response")
    aliases = {
        "id": ("id", "ID"),
        "title": ("title", "post_title"),
        "slug": ("slug", "post_name"),
        "status": ("status", "post_status"),
        "modified": ("modified", "post_modified", "post_modified_gmt"),
        "date": ("date", "post_date", "post_date_gmt"),
        "link": ("link", "url", "guid"),
        "content": ("content", "post_content"),
    }
    page: dict[str, Any] = {}
    for name, keys in aliases.items():
        if name == "content" and not include_content:
            continue
        page[name] = next((raw[key] for key in keys if key in raw), "")
    if page.get("id") not in (None, ""):
        page["id"] = _page_id(page["id"])
    if include_content and not isinstance(page.get("content"), str):
        page["content"] = "" if page.get("content") is None else str(page["content"])
    return page


def _read_page(site_config, page_id: int) -> dict:
    if site_config.transport == "ssh":
        raw = ssh_wpcli.run_wp_cli_json(
            site_config,
            [
                "post", "get", str(page_id), "--post_type=page",
                "--fields=ID,post_type,post_title,post_name,post_status,post_modified,post_date,guid,post_content",
            ],
        )
        if isinstance(raw, dict) and raw.get("post_type") != "page":
            raise ValueError(f"post {page_id} is not a WordPress page")
    else:
        raw = companion_plugin.call(site_config, "page_get", {"post_id": page_id})
    return _normalize_page(raw)


def _page_context(page: dict) -> dict:
    content = page["content"]
    return {
        key: page.get(key, "")
        for key in ("id", "title", "slug", "status", "modified", "date", "link")
    } | {"content_sha256": _sha256(content), "content_length": len(content), "etag": _etag(content)}


def _bounded_diff(before: str, after: str, max_chars: int) -> dict:
    if max_chars < 500 or max_chars > MAX_DIFF_MAX_CHARS:
        raise ValueError(f"diff_max_chars must be between 500 and {MAX_DIFF_MAX_CHARS}")
    full = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="target/current",
            tofile="target/proposed",
            n=3,
        )
    )
    truncated = len(full) > max_chars
    shown = full[:max_chars]
    if truncated:
        shown += f"\n... diff truncated; {len(full) - max_chars} characters omitted ...\n"
    return {
        "text": wrap_untrusted(shown, field="unified_diff"),
        "truncated": truncated,
        "shown_chars": min(len(full), max_chars),
        "complete_chars": len(full),
        "complete_sha256": _sha256(full),
    }


def _protected_copy_report(current: str, proposed: str, protected_copy: list[str] | None) -> dict:
    values = protected_copy or []
    if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
        raise ValueError("protected_copy must be a list of nonempty exact strings")
    checks = []
    for value in values:
        present_before = value in current
        present_after = value in proposed
        status = "preserved" if present_before and present_after else (
            "missing" if present_before else "not_present_in_target"
        )
        checks.append({
            "text_sha256": _sha256(value),
            "length": len(value),
            "present_before": present_before,
            "present_after": present_after,
            "status": status,
        })
    missing = sum(check["status"] == "missing" for check in checks)
    return {
        "status": "fail" if missing else ("pass" if checks else "not_configured"),
        "checked": len(checks),
        "missing": missing,
        "checks": checks,
    }


def wp_page_list(site: str, status: str = "publish", search: str = "", limit: int = DEFAULT_PAGE_LIMIT) -> dict:
    """List pages with bounded metadata. Read-only and safe to call before opening a packet."""
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_PAGE_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_LIMIT}")
    site_config = get_site_registry().get(site)
    if site_config.transport == "ssh":
        args = [
            "post", "list", "--post_type=page", f"--posts_per_page={limit}",
            "--orderby=modified", "--order=DESC",
            "--fields=ID,post_title,post_name,post_status,post_modified,post_date,guid",
        ]
        if status:
            args.append(f"--post_status={status}")
        if search:
            args.append(f"--s={search}")
        raw = ssh_wpcli.run_wp_cli_json(site_config, args) or []
    else:
        response = companion_plugin.call(
            site_config,
            "page_list",
            {"post_status": status, "search": search, "per_page": limit, "page": 1},
        ) or {}
        raw = response.get("pages", []) if isinstance(response, dict) else response
    if not isinstance(raw, list):
        raise ValueError("WordPress returned an invalid page list")
    pages = [_normalize_page(item, include_content=False) for item in raw[:limit]]
    return {"site": site, "count": len(pages), "limit": limit, "pages": pages}


def wp_page_get(site: str, page_id: int) -> dict:
    """Read one page and return its metadata, complete content hash, and untrusted content envelope."""
    page_id = _page_id(page_id)
    page = _read_page(get_site_registry().get(site), page_id)
    content = page.pop("content")
    return {
        "site": site,
        "page": {**page, "content_sha256": _sha256(content), "etag": _etag(content),
                 "content_length": len(content),
                 "content": wrap_untrusted(content, field=f"page:{page_id}:content")},
    }


def wp_page_compare(
    site: str,
    target_page_id: int,
    reference_page_id: int,
    protected_copy: list[str] | None = None,
    diff_max_chars: int = DEFAULT_DIFF_MAX_CHARS,
) -> dict:
    """Compare a target page to an approved reference without changing either page."""
    target_page_id = _page_id(target_page_id)
    reference_page_id = _page_id(reference_page_id)
    if target_page_id == reference_page_id:
        raise ValueError("target_page_id and reference_page_id must be different")
    site_config = get_site_registry().get(site)
    target = _read_page(site_config, target_page_id)
    reference = _read_page(site_config, reference_page_id)
    target_content = target["content"]
    reference_content = reference["content"]
    correction_report = evaluate_corrections(site, f"post:{target_page_id}:content", reference_content)
    return {
        "site": site,
        "target": _page_context(target),
        "reference": _page_context(reference),
        "same_content": target_content == reference_content,
        "diff": _bounded_diff(target_content, reference_content, diff_max_chars),
        "corrections": correction_report,
        "protected_copy": _protected_copy_report(target_content, reference_content, protected_copy),
        "note": "Comparison only. Reference content is not applied by this tool.",
    }


def wp_page_replace_content(
    site: str,
    page_id: int,
    new_content: str,
    apply: bool = False,
    expected_etag: str | None = None,
    reference_page_id: int | None = None,
    protected_copy: list[str] | None = None,
    diff_max_chars: int = DEFAULT_DIFF_MAX_CHARS,
) -> dict:
    """Preview or replace a page body with exact content under packet, correction, and ETag guards."""
    page_id = _page_id(page_id)
    if not isinstance(new_content, str):
        raise ValueError("new_content must be a string")
    if reference_page_id is not None:
        reference_page_id = _page_id(reference_page_id)
        if reference_page_id == page_id:
            raise ValueError("reference_page_id must differ from page_id")

    site_config = get_site_registry().get(site)
    current = _read_page(site_config, page_id)
    current_content = current["content"]
    current_etag = _etag(current_content)
    target = f"post:{page_id}:content"
    payload = {
        "page_id": page_id,
        "new_content_sha256": _sha256(new_content),
        "reference_page_id": reference_page_id,
        "protected_copy_sha256": [_sha256(value) for value in (protected_copy or [])],
    }
    change_digest = build_change_digest(site, "wp_page_replace_content", target, current_etag, payload)
    corrections = evaluate_corrections(site, target, new_content)
    protected_report = _protected_copy_report(current_content, new_content, protected_copy)
    reference_context = None
    if reference_page_id is not None:
        reference_context = _page_context(_read_page(site_config, reference_page_id))
    preview = {
        "site": site,
        "dry_run": not apply,
        "applied": False,
        "target": _page_context(current),
        "reference": reference_context,
        "proposed": {"content_sha256": _sha256(new_content), "content_length": len(new_content)},
        "etag": current_etag,
        "change_digest": change_digest,
        "diff": _bounded_diff(current_content, new_content, diff_max_chars),
        "corrections": corrections,
        "protected_copy": protected_report,
    }
    if not apply:
        return preview

    if expected_etag is None:
        raise ValueError("expected_etag from the reviewed preview is required when apply=True")
    actual_etag = _etag(current_content)
    if expected_etag is not None and expected_etag != actual_etag:
        raise ConflictError(
            "page changed since preview: refusing to overwrite; preview the current page again",
            expected_etag=expected_etag,
            actual_etag=actual_etag,
        )
    assert_corrections_allow(corrections)
    if protected_report["status"] == "fail":
        raise ValueError("proposed content removes protected copy; inspect the preview report")
    packet = require_approved_packet(
        get_packet_store(), site, target=target, change_digest=change_digest
    )
    snapshot = get_snapshot_store().record(
        packet_id=packet.id,
        site=site,
        tool="wp_page_replace_content",
        target=target,
        previous_value=current_content,
        new_value=new_content,
        reread=["post_content", page_id],
    )
    if site_config.transport == "ssh":
        ssh_wpcli.run_wp_cli(site_config, ["post", "update", str(page_id), f"--post_content={new_content}"])
    else:
        companion_plugin.call(
            site_config,
            "page_replace_content",
            {
                "post_id": page_id,
                "new_content": new_content,
                "expected_content_sha256": _sha256(current_content),
            },
        )
    reread = _read_page(site_config, page_id)
    reread_content = reread["content"]
    verified = _sha256(reread_content) == _sha256(new_content)
    get_packet_store().log(
        packet.id,
        f"applied wp_page_replace_content(page {page_id}) -- snapshot {snapshot.id}; "
        f"read-back {'passed' if verified else 'failed'}",
    )
    return {
        **preview,
        "dry_run": False,
        "applied": True,
        "packet_id": packet.id,
        "snapshot_id": snapshot.id,
        "verification": {
            "status": "pass" if verified else "fail",
            "expected_content_sha256": _sha256(new_content),
            "observed_content_sha256": _sha256(reread_content),
            "observed_modified": reread.get("modified", ""),
            "note": "Stored-content read-back only; rendered desktop and mobile review remains separate.",
        },
    }


GUARDED_TOOLS = {"wp_page_replace_content": wp_page_replace_content}
