"""Human corrections remain enforced on both transports, including bypass mode."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from wpguard_mcp import corrections
from wpguard_mcp.config import SiteConfig
from wpguard_mcp.corrections import CorrectionBlockedError, CorrectionStore
from wpguard_mcp.guard import PacketRequiredError
from wpguard_mcp.tools import mutate, packets


@pytest.fixture()
def correction_flow(wired, monkeypatch, tmp_path, request):
    transport, verb = request.param
    store = CorrectionStore(tmp_path / "corrections.jsonl")
    monkeypatch.setattr(corrections, "get_correction_store", lambda: store)
    monkeypatch.delenv("WPGUARD_BYPASS_GUARD", raising=False)
    state = wired["state"]
    state["values"].update({
        ("option", "blogname"): "old",
        ("post_meta", 7, "faq"): "old",
        ("content", 7): "old",
    })
    companion_state = {"previous_content": "old", "supports_expected_content_sha256": True}
    if transport == "companion_plugin":
        site = SiteConfig(
            name="example", transport="companion_plugin", plugin_url="https://example.test/wp-json/wpguard/v1/exec",
            plugin_api_key_env="TEST_WPGUARD_KEY",
        )
        monkeypatch.setattr(mutate, "get_site_registry", lambda: SimpleNamespace(get=lambda name: site))

        def call(config, command, args=None):
            args = args or {}
            if command in {"get_option", "get_post_meta"}:
                return "old"
            if command == "search_replace_post_content" and not args["apply"]:
                return {"match_count": 1, **companion_state}
            state["writes"].append((command, args))
            return {"match_count": 1}

        monkeypatch.setattr(mutate.companion_plugin, "call", call)

    targets = {"option": "option:blogname", "meta": "post:7:faq", "content": "post:7:content"}
    correction_targets = {**targets, "meta": "post_meta:7:faq"}

    def invoke(value="bad", apply=False, site="example"):
        if verb == "option":
            return mutate.wp_mutate_option(site, "blogname", value, apply=apply)
        if verb == "meta":
            return mutate.wp_mutate_post_meta(site, 7, "faq", value, apply=apply)
        return mutate.wp_mutate_post_content(site, 7, "old", value, apply=apply)

    def record(site="example", target=None):
        return store.record(
            site=site, target=target or correction_targets[verb],
            human_correction="Preserve the accepted heading", source_ref="marker:example:42",
            kind="equals", expected="good", rejected_value="bad", accepted_value="good",
            human_requested_basis="Client requested this exact heading in ticket 42",
        )

    def approve():
        packet = packets.packet_open(site="example", summary="heading correction", target=targets[verb])
        packets.packet_approve(packet_id=packet["id"], approver="alice")
        return packet

    return dict(wired, store=store, invoke=invoke, record=record, approve=approve,
                companion_state=companion_state)


CASES = [(transport, verb) for transport in ("ssh", "companion_plugin")
         for verb in ("option", "meta", "content")]


@pytest.mark.parametrize("correction_flow", CASES, indirect=True)
@pytest.mark.parametrize("bypass", [False, True])
def test_regression_refused_before_snapshot_or_write(correction_flow, monkeypatch, bypass):
    flow = correction_flow
    rule = flow["record"]()
    assert rule["replay"] == {"rejected": {"status": "fail"}, "accepted": {"status": "pass"}}
    preview = flow["invoke"]()
    assert preview["corrections"]["status"] == "fail"
    assert preview["corrections"]["checks"][0]["source_ref"] == "marker:example:42"
    assert flow["state"]["writes"] == []
    packet = flow["approve"]()
    if bypass:
        monkeypatch.setenv("WPGUARD_BYPASS_GUARD", "1")
    with pytest.raises(CorrectionBlockedError):
        flow["invoke"](apply=True)
    assert flow["state"]["writes"] == []
    assert flow["snapshot_store"].list_for_packet(packet["id"]) == []
    assert not flow["snapshot_store"].path.exists()


@pytest.mark.parametrize("correction_flow", [(t, "content") for t in ("ssh", "companion_plugin")], indirect=True)
@pytest.mark.parametrize("rule_target", ["post:7:content", "post_meta:7:content"])
def test_body_and_meta_named_content_have_separate_corrections(correction_flow, rule_target):
    flow = correction_flow
    flow["record"](target=rule_target)
    body = flow["invoke"]()["corrections"]
    meta = mutate.wp_mutate_post_meta("example", 7, "content", "bad")["corrections"]
    assert body["target"] == "post:7:content"
    assert meta["target"] == "post_meta:7:content"
    assert body["status"] == ("fail" if rule_target == body["target"] else "not_covered")
    assert meta["status"] == ("fail" if rule_target == meta["target"] else "not_covered")


@pytest.mark.parametrize("correction_flow", [(t, "option") for t in ("ssh", "companion_plugin")], indirect=True)
@pytest.mark.parametrize("name", ["settings[0]", "literal*key", "question?key"])
@pytest.mark.parametrize("verb", ["option", "meta"])
def test_literal_key_characters_remain_usable_without_rules(correction_flow, name, verb):
    if verb == "option":
        preview = mutate.wp_mutate_option("example", name, "bad")
        expected_target = f"option:{name}"
    else:
        preview = mutate.wp_mutate_post_meta("example", 7, name, "bad")
        expected_target = f"post_meta:7:{name}"
    assert preview["corrections"]["target"] == expected_target
    assert preview["corrections"]["status"] == "not_covered"
    assert correction_flow["state"]["writes"] == []
    correction_flow["record"](target=expected_target)
    if verb == "option":
        exact = mutate.wp_mutate_option("example", name, "bad")
        different = mutate.wp_mutate_option("example", name + "other", "bad")
    else:
        exact = mutate.wp_mutate_post_meta("example", 7, name, "bad")
        different = mutate.wp_mutate_post_meta("example", 7, name + "other", "bad")
    assert exact["corrections"]["status"] == "fail"
    assert different["corrections"]["status"] == "not_covered"


@pytest.mark.parametrize("correction_flow", CASES, indirect=True)
def test_accepted_correction_still_requires_approval_then_writes(correction_flow):
    flow = correction_flow
    flow["record"]()
    assert flow["invoke"]("good")["corrections"]["status"] == "pass"
    with pytest.raises(PacketRequiredError):
        flow["invoke"]("good", apply=True)
    assert flow["state"]["writes"] == []
    packet = flow["approve"]()
    assert flow["invoke"]("good", apply=True)["applied"] is True
    assert len(flow["state"]["writes"]) == 1
    snapshots = flow["snapshot_store"].list_for_packet(packet["id"])
    assert len(snapshots) == 1
    assert snapshots[0].new_value == "good"


@pytest.mark.parametrize("correction_flow", CASES, indirect=True)
@pytest.mark.parametrize("scope", ["wrong_site", "wrong_target", "empty"])
def test_uncovered_target_does_not_inherit_another_correction(correction_flow, scope):
    flow = correction_flow
    if scope == "wrong_site":
        flow["record"](site="another-client")
    elif scope == "wrong_target":
        flow["record"](target="post:99:content")
    report = flow["invoke"]()["corrections"]
    assert report["status"] == "not_covered"
    assert report["checks"] == []
    flow["approve"]()
    assert flow["invoke"](apply=True)["applied"] is True


@pytest.mark.parametrize("correction_flow", [("companion_plugin", "content")], indirect=True)
@pytest.mark.parametrize("bypass", [False, True])
def test_companion_missing_content_is_unknown_and_cannot_write(correction_flow, monkeypatch, bypass):
    flow = correction_flow
    flow["record"]()
    flow["companion_state"].clear()
    assert flow["invoke"]("good")["corrections"]["status"] == "unknown"
    packet = flow["approve"]()
    if bypass:
        monkeypatch.setenv("WPGUARD_BYPASS_GUARD", "1")
    with pytest.raises(CorrectionBlockedError):
        flow["invoke"]("good", apply=True)
    assert flow["state"]["writes"] == []
    assert flow["snapshot_store"].list_for_packet(packet["id"]) == []
    assert not flow["snapshot_store"].path.exists()


@pytest.mark.parametrize("correction_flow", [(t, "content") for t in ("ssh", "companion_plugin")], indirect=True)
@pytest.mark.parametrize("apply", [False, True])
def test_empty_search_rejected_before_transport(correction_flow, monkeypatch, apply):
    def unexpected_call(*args, **kwargs):
        pytest.fail("empty search must not reach the transport")

    monkeypatch.setattr(mutate.ssh_wpcli, "run_wp_cli", unexpected_call)
    monkeypatch.setattr(mutate.companion_plugin, "call", unexpected_call)
    with pytest.raises(ValueError, match="search must not be empty"):
        mutate.wp_mutate_post_content("example", 7, "", "good", apply=apply)


@pytest.mark.parametrize("correction_flow", [("companion_plugin", "content")], indirect=True)
@pytest.mark.parametrize("bypass", [False, True])
def test_companion_capability_required_for_applicable_corrections(correction_flow, monkeypatch, bypass):
    flow = correction_flow
    flow["record"]()
    flow["companion_state"].pop("supports_expected_content_sha256")
    report = flow["invoke"]("good")["corrections"]
    assert report["status"] == "unknown"
    assert "update the companion plugin" in report["reason"]
    flow["approve"]()
    if bypass:
        monkeypatch.setenv("WPGUARD_BYPASS_GUARD", "1")
    with pytest.raises(CorrectionBlockedError):
        flow["invoke"]("good", apply=True)
    assert flow["state"]["writes"] == []
    assert not flow["snapshot_store"].path.exists()


@pytest.mark.parametrize("correction_flow", [("companion_plugin", "content")], indirect=True)
def test_companion_apply_sends_full_source_digest(correction_flow):
    flow = correction_flow
    # UTF-8 matters: the digest must cover exactly what PHP reads.
    flow["companion_state"]["previous_content"] = "café old"
    flow["approve"]()
    assert flow["invoke"]("good", apply=True)["applied"] is True
    command, args = flow["state"]["writes"][0]
    assert command == "search_replace_post_content"
    assert args["expected_content_sha256"] == hashlib.sha256("café old".encode()).hexdigest()


@pytest.mark.parametrize("correction_flow", [("companion_plugin", "content")], indirect=True)
def test_companion_stale_source_refusal_propagates_without_write(correction_flow, monkeypatch):
    flow = correction_flow
    flow["record"]()
    flow["approve"]()
    original_call = mutate.companion_plugin.call

    def changed_between_preview_and_apply(config, command, args=None):
        if command == "search_replace_post_content" and args["apply"]:
            assert args["expected_content_sha256"] == hashlib.sha256(b"old").hexdigest()
            raise mutate.companion_plugin.CompanionPluginError("content changed", 409)
        return original_call(config, command, args)

    monkeypatch.setattr(mutate.companion_plugin, "call", changed_between_preview_and_apply)
    with pytest.raises(mutate.companion_plugin.CompanionPluginError) as error:
        flow["invoke"]("good", apply=True)
    assert error.value.status_code == 409
    assert flow["state"]["writes"] == []
