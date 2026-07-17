"""End-to-end propose -> approve -> apply flow, optimistic concurrency (#6),
and durable re-verify on close (#2), exercised through the fake SSH transport.
"""
from __future__ import annotations

import pytest

from wpguard_mcp.guard import ConflictError, PacketRequiredError
from wpguard_mcp.tools import mutate, packets


def test_apply_requires_approval_then_writes(wired):
    state = wired["state"]
    state["values"][("option", "blogname")] = "old"

    # Proposed but not approved -> still blocked.
    packet = packets.packet_open(site="example", summary="rename", target="option:blogname")
    with pytest.raises(PacketRequiredError):
        mutate.wp_mutate_option(site="example", option_name="blogname", new_value="new", apply=True)

    # Approve, then it goes through.
    packets.packet_approve(packet_id=packet["id"], approver="alice")
    result = mutate.wp_mutate_option(site="example", option_name="blogname", new_value="new", apply=True)

    assert result["applied"] is True
    assert result["packet_id"] == packet["id"]
    assert ["option", "update", "blogname", "new"] in state["writes"]

    snaps = wired["snapshot_store"].list_for_packet(packet["id"])
    assert len(snaps) == 1
    assert snaps[0].previous_value == "old"
    assert snaps[0].new_value == "new"
    assert snaps[0].reread == ["option", "blogname"]


def test_dry_run_returns_etag_and_apply_rejects_stale_etag(wired):
    state = wired["state"]
    state["values"][("option", "blogname")] = "old"

    preview = mutate.wp_mutate_option(site="example", option_name="blogname", new_value="new")
    assert preview["dry_run"] is True
    etag = preview["etag"]

    packet = packets.packet_open(site="example", summary="rename", target="option:blogname")
    packets.packet_approve(packet_id=packet["id"], approver="alice")

    # Someone else changed the value out from under us.
    state["values"][("option", "blogname")] = "changed-by-someone-else"

    with pytest.raises(ConflictError):
        mutate.wp_mutate_option(
            site="example", option_name="blogname", new_value="new", apply=True, expected_etag=etag
        )
    # No write happened.
    assert ["option", "update", "blogname", "new"] not in state["writes"]


def test_matching_etag_allows_apply(wired):
    state = wired["state"]
    state["values"][("option", "blogname")] = "old"
    preview = mutate.wp_mutate_option(site="example", option_name="blogname", new_value="new")

    packet = packets.packet_open(site="example", summary="rename", target="option:blogname")
    packets.packet_approve(packet_id=packet["id"], approver="alice")

    result = mutate.wp_mutate_option(
        site="example", option_name="blogname", new_value="new", apply=True, expected_etag=preview["etag"]
    )
    assert result["applied"] is True


def test_exact_change_packet_allows_only_previewed_payload(wired):
    state = wired["state"]
    state["values"][("option", "blogname")] = "old"
    preview = mutate.wp_mutate_option(site="example", option_name="blogname", new_value="approved")

    packet = packets.packet_open(
        site="example",
        summary="rename",
        target="option:blogname",
        verb="wp_mutate_option",
        change_digest=preview["change_digest"],
    )
    packets.packet_approve(packet_id=packet["id"], approver="alice")

    with pytest.raises(PacketRequiredError, match="bound to a different change digest"):
        mutate.wp_mutate_option(
            site="example",
            option_name="blogname",
            new_value="different",
            apply=True,
            expected_etag=preview["etag"],
        )

    result = mutate.wp_mutate_option(
        site="example",
        option_name="blogname",
        new_value="approved",
        apply=True,
        expected_etag=preview["etag"],
    )
    assert result["applied"] is True


def test_durable_check_passes_when_value_sticks(wired):
    state = wired["state"]
    state["values"][("option", "blogname")] = "old"
    packet = packets.packet_open(site="example", summary="rename", target="option:blogname")
    packets.packet_approve(packet_id=packet["id"], approver="alice")
    mutate.wp_mutate_option(site="example", option_name="blogname", new_value="new", apply=True)

    # The write stuck: current value == written value.
    state["values"][("option", "blogname")] = "new"
    closed = packets.packet_close(packet_id=packet["id"], outcome="done", durable_check_delay_seconds=0)

    assert closed["durable_check"]["durable"] is True
    assert closed["outcome"] == "done"


def test_durable_check_fails_when_value_reverts(wired):
    state = wired["state"]
    state["values"][("option", "blogname")] = "old"
    packet = packets.packet_open(site="example", summary="rename", target="option:blogname")
    packets.packet_approve(packet_id=packet["id"], approver="alice")
    mutate.wp_mutate_option(site="example", option_name="blogname", new_value="new", apply=True)

    # Something reverted it back after the write.
    state["values"][("option", "blogname")] = "old"
    closed = packets.packet_close(packet_id=packet["id"], outcome="done", durable_check_delay_seconds=0)

    assert closed["durable_check"]["durable"] is False
    assert closed["outcome"].startswith("verify_failed")


def test_eval_fires_and_is_ssh_gated(wired):
    state = wired["state"]
    preview = mutate.wp_eval(site="example", php_code="echo 1;")
    packet = packets.packet_open(
        site="example",
        summary="raw fix",
        target="raw_php_eval",
        verb="wp_eval",
        change_digest=preview["change_digest"],
    )
    packets.packet_approve(packet_id=packet["id"], approver="alice")

    result = mutate.wp_eval(site="example", php_code="echo 1;", apply=True)
    assert result["applied"] is True
    assert state["eval_calls"] == ["echo 1;"]
