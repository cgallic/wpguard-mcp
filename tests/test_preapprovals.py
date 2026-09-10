from __future__ import annotations

import pytest

from wpguard_mcp.preapproval import PreapprovalStore


def test_policy_matches_exact_source_verb_target_and_risk(tmp_path):
    store = PreapprovalStore(tmp_path / "policies.jsonl")
    policy = store.create(
        name="cache sync",
        site="example",
        source="cron:nightly",
        verbs=["wp_cache_bust"],
        target_pattern="cache:*",
        max_risk="low",
        approver="owner",
    )
    assert (
        store.match(site="example", source="cron:nightly", verb="wp_cache_bust", target="cache:all", risk="low")
        == policy
    )
    assert (
        store.match(site="example", source="cron:other", verb="wp_cache_bust", target="cache:all", risk="low") is None
    )
    assert store.match(site="example", source="cron:nightly", verb="wp_eval", target="cache:all", risk="low") is None
    assert (
        store.match(site="example", source="cron:nightly", verb="wp_cache_bust", target="cache:all", risk="high")
        is None
    )


def test_retired_policy_no_longer_matches(tmp_path):
    store = PreapprovalStore(tmp_path / "policies.jsonl")
    policy = store.create(
        name="safe",
        site="example",
        source="hook:a",
        verbs=["wp_cache_bust"],
        target_pattern="cache:*",
        max_risk="low",
        approver="owner",
    )
    store.retire(policy.id)
    assert store.match(site="example", source="hook:a", verb="wp_cache_bust", target="cache:all", risk="low") is None


def test_wildcard_verbs_rejected(monkeypatch):
    from wpguard_mcp.tools import preapprovals

    with pytest.raises(ValueError, match="wildcard verbs"):
        preapprovals.wp_preapproval_create("bad", "site", "cron", ["*"], "*", "owner")
