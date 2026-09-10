from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from wpguard_mcp import corrections
from wpguard_mcp.config import SiteConfig
from wpguard_mcp.corrections import CorrectionBlockedError, CorrectionStore
from wpguard_mcp.guard import ConflictError, PacketRequiredError
from wpguard_mcp.tools import packets, pages
from wpguard_mcp.transports import ssh_wpcli


@pytest.fixture()
def page_flow(monkeypatch, stores, ssh_site, tmp_path):
    packet_store, snapshot_store = stores
    registry = SimpleNamespace(get=lambda _name: ssh_site)
    monkeypatch.setattr(pages, "get_site_registry", lambda: registry)
    monkeypatch.setattr(pages, "get_packet_store", lambda: packet_store)
    monkeypatch.setattr(pages, "get_snapshot_store", lambda: snapshot_store)
    monkeypatch.setattr(packets, "get_site_registry", lambda: registry)
    monkeypatch.setattr(packets, "get_packet_store", lambda: packet_store)
    monkeypatch.setattr(packets, "get_snapshot_store", lambda: snapshot_store)
    correction_store = CorrectionStore(tmp_path / "corrections.jsonl")
    monkeypatch.setattr(corrections, "get_correction_store", lambda: correction_store)
    monkeypatch.delenv("WPGUARD_BYPASS_GUARD", raising=False)

    state = {
        7: {"ID": 7, "post_type": "page", "post_title": "Target", "post_name": "target", "post_status": "publish",
            "post_modified": "2026-09-10 10:00:00", "post_date": "2026-09-01 10:00:00",
            "guid": "https://example.test/target/", "post_content": "<h2>Keep this</h2>\nOld"},
        9: {"ID": 9, "post_type": "page", "post_title": "Reference", "post_name": "reference", "post_status": "publish",
            "post_modified": "2026-09-10 09:00:00", "post_date": "2026-08-01 10:00:00",
            "guid": "https://example.test/reference/", "post_content": "<h2>Keep this</h2>\nBetter"},
    }
    writes = []

    def run_json(_site, args, timeout=60):
        if args[:2] == ["post", "list"]:
            return list(state.values())
        return dict(state[int(args[2])])

    def run_cli(_site, args, timeout=60):
        writes.append(args)
        if args[:2] == ["post", "update"]:
            state[int(args[2])]["post_content"] = args[3].split("=", 1)[1]
        return ssh_wpcli.CommandResult(0, "", "")

    monkeypatch.setattr(pages.ssh_wpcli, "run_wp_cli_json", run_json)
    monkeypatch.setattr(pages.ssh_wpcli, "run_wp_cli", run_cli)
    return {"state": state, "writes": writes, "packet_store": packet_store,
            "snapshot_store": snapshot_store, "corrections": correction_store}


def test_list_and_get_return_bounded_context_and_complete_hashes(page_flow):
    listed = pages.wp_page_list("example", limit=1)
    assert listed["count"] == 1
    assert listed["pages"][0]["id"] == 7
    assert "content" not in listed["pages"][0]

    result = pages.wp_page_get("example", 7)["page"]
    content = page_flow["state"][7]["post_content"]
    assert result["content_sha256"] == hashlib.sha256(content.encode()).hexdigest()
    assert result["etag"] == result["content_sha256"][:16]
    assert result["content"]["untrusted_content"] == content


def test_page_tools_have_least_privilege_policy_tiers():
    from wpguard_mcp import policy

    assert policy.TOOL_TIERS["wp_page_list"] == 1
    assert policy.TOOL_TIERS["wp_page_get"] == 1
    assert policy.TOOL_TIERS["wp_page_compare"] == 1
    assert policy.TOOL_TIERS["wp_page_replace_content"] == 2


def test_compare_returns_context_diff_corrections_and_protected_copy(page_flow):
    result = pages.wp_page_compare("example", 7, 9, protected_copy=["Keep this"])
    assert result["target"]["id"] == 7
    assert result["reference"]["id"] == 9
    assert result["diff"]["complete_sha256"]
    assert "-Old" in result["diff"]["text"]["untrusted_content"]
    assert "+Better" in result["diff"]["text"]["untrusted_content"]
    assert result["protected_copy"]["status"] == "pass"
    assert result["corrections"]["status"] == "not_covered"


def test_replace_preview_then_exact_approved_apply_records_snapshot(page_flow):
    new_content = "<h2>Keep this</h2>\nFinished"
    preview = pages.wp_page_replace_content(
        "example", 7, new_content, reference_page_id=9, protected_copy=["Keep this"]
    )
    assert preview["dry_run"] is True
    assert preview["applied"] is False
    assert preview["proposed"]["content_sha256"] == hashlib.sha256(new_content.encode()).hexdigest()
    with pytest.raises(PacketRequiredError):
        pages.wp_page_replace_content("example", 7, new_content, apply=True,
                                      expected_etag=preview["etag"], reference_page_id=9,
                                      protected_copy=["Keep this"])

    packet = packets.packet_open(site="example", summary="Finish target page",
                                 target="post:7:content", verb="wp_page_replace_content",
                                 change_digest=preview["change_digest"])
    packets.packet_approve(packet["id"], "owner")
    result = pages.wp_page_replace_content("example", 7, new_content, apply=True,
                                           expected_etag=preview["etag"], reference_page_id=9,
                                           protected_copy=["Keep this"])
    assert result["applied"] is True
    assert result["verification"]["status"] == "pass"
    assert page_flow["state"][7]["post_content"] == new_content
    snapshots = page_flow["snapshot_store"].list_for_packet(packet["id"])
    assert len(snapshots) == 1
    assert snapshots[0].previous_value.endswith("Old")
    assert snapshots[0].new_value == new_content
    assert snapshots[0].reread == ["post_content", 7]


def test_replace_refuses_stale_etag_before_snapshot_or_write(page_flow):
    preview = pages.wp_page_replace_content("example", 7, "New")
    page_flow["state"][7]["post_content"] = "Human edit"
    packet = packets.packet_open(site="example", summary="Replace", target="post:7:content")
    packets.packet_approve(packet["id"], "owner")
    with pytest.raises(ConflictError):
        pages.wp_page_replace_content("example", 7, "New", apply=True, expected_etag=preview["etag"])
    assert page_flow["writes"] == []
    assert page_flow["snapshot_store"].list_for_packet(packet["id"]) == []


def test_replace_requires_reviewed_etag_on_apply(page_flow):
    preview = pages.wp_page_replace_content("example", 7, "New")
    packet = packets.packet_open(site="example", summary="Replace", target="post:7:content",
                                 verb="wp_page_replace_content", change_digest=preview["change_digest"])
    packets.packet_approve(packet["id"], "owner")
    with pytest.raises(ValueError, match="expected_etag"):
        pages.wp_page_replace_content("example", 7, "New", apply=True)
    assert page_flow["writes"] == []


def test_replace_refuses_removed_protected_copy_before_snapshot_or_write(page_flow):
    packet = packets.packet_open(site="example", summary="Replace", target="post:7:content")
    packets.packet_approve(packet["id"], "owner")
    preview = pages.wp_page_replace_content("example", 7, "No heading", protected_copy=["Keep this"])
    with pytest.raises(ValueError, match="protected copy"):
        pages.wp_page_replace_content("example", 7, "No heading", apply=True,
                                      expected_etag=preview["etag"], protected_copy=["Keep this"])
    assert page_flow["writes"] == []
    assert page_flow["snapshot_store"].list_for_packet(packet["id"]) == []


def test_replace_refuses_failed_correction(page_flow):
    page_flow["corrections"].record(
        site="example", target="post:7:content", human_correction="Keep the approved heading",
        source_ref="review:synthetic:1", human_requested_basis="Synthetic test request",
        kind="contains", expected="Approved heading", rejected_value="No heading",
        accepted_value="Approved heading",
    )
    packet = packets.packet_open(site="example", summary="Replace", target="post:7:content")
    packets.packet_approve(packet["id"], "owner")
    preview = pages.wp_page_replace_content("example", 7, "No heading")
    with pytest.raises(CorrectionBlockedError):
        pages.wp_page_replace_content("example", 7, "No heading", apply=True, expected_etag=preview["etag"])
    assert page_flow["writes"] == []


def test_diff_is_bounded_but_hash_covers_complete_diff(page_flow):
    page_flow["state"][9]["post_content"] = "\n".join(f"new-{i}" for i in range(500))
    result = pages.wp_page_compare("example", 7, 9, diff_max_chars=500)
    assert result["diff"]["truncated"] is True
    assert result["diff"]["complete_chars"] > result["diff"]["shown_chars"]
    assert len(result["diff"]["complete_sha256"]) == 64


def test_companion_uses_page_command_contract(monkeypatch, stores, tmp_path):
    packet_store, snapshot_store = stores
    site_config = SiteConfig(name="companion", transport="companion_plugin",
                             plugin_url="https://example.test/wp-json/wpguard/v1/exec",
                             plugin_api_key_env="TEST_KEY")
    monkeypatch.setattr(pages, "get_site_registry", lambda: SimpleNamespace(get=lambda _name: site_config))
    monkeypatch.setattr(pages, "get_packet_store", lambda: packet_store)
    monkeypatch.setattr(pages, "get_snapshot_store", lambda: snapshot_store)
    monkeypatch.setattr(corrections, "get_correction_store", lambda: CorrectionStore(tmp_path / "c.jsonl"))
    calls = []
    page = {"id": 7, "title": "Target", "slug": "target", "status": "publish",
            "modified": "now", "link": "https://example.test/target/", "content": "Old"}

    def call(_site, command, args=None):
        calls.append((command, args))
        if command == "page_list":
            return {"pages": [page], "page": 1, "per_page": 20}
        if command == "page_get":
            return page
        page["content"] = args["new_content"]
        return {"updated": True, "page": {**page, "content": args["new_content"]}}

    monkeypatch.setattr(pages.companion_plugin, "call", call)
    assert pages.wp_page_list("companion")["count"] == 1
    preview = pages.wp_page_replace_content("companion", 7, "New")
    packet = packet_store.open_packet("companion", "Replace", target="post:7:content",
                                      verb="wp_page_replace_content", change_digest=preview["change_digest"])
    packet_store.approve_packet(packet.id, "owner")
    pages.wp_page_replace_content("companion", 7, "New", apply=True, expected_etag=preview["etag"])
    assert calls[0] == ("page_list", {"post_status": "publish", "search": "", "per_page": 20, "page": 1})
    assert calls[-2][0] == "page_replace_content"
    assert calls[-2][1]["post_id"] == 7
    assert calls[-2][1]["expected_content_sha256"] == hashlib.sha256(b"Old").hexdigest()
    assert calls[-1][0] == "page_get"
