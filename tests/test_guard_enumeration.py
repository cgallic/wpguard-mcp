"""Issue #1: every registered Tier 2/3 tool must funnel its apply=True write
through the one shared guard, `require_approved_packet`. This test enumerates
the canonical GUARDED_TOOLS registry and asserts each one calls the shared gate
-- so a new guarded tool added later cannot silently skip approval.
"""
from __future__ import annotations

import pytest

from wpguard_mcp.guard import PacketRequiredError
from wpguard_mcp.tools import mutate

# Minimal apply=True kwargs for each guarded tool.
APPLY_KWARGS = {
    "wp_mutate_option": {"option_name": "blogname", "new_value": "x", "apply": True},
    "wp_mutate_post_meta": {"post_id": 1, "meta_key": "k", "new_value": "x", "apply": True},
    "wp_mutate_post_content": {"post_id": 1, "search": "a", "replace": "b", "apply": True},
    "wp_eval": {"php_code": "echo 1;", "apply": True},
}


def test_every_guarded_tool_is_covered_by_apply_kwargs():
    # If someone adds a guarded tool but forgets to give this test kwargs for
    # it, fail loudly rather than silently skipping it.
    assert set(mutate.GUARDED_TOOLS) == set(APPLY_KWARGS)


@pytest.mark.parametrize("tool_name", sorted(mutate.GUARDED_TOOLS))
def test_guarded_tool_calls_shared_gate(tool_name, wired, monkeypatch):
    calls = []

    def spy(store, site):
        calls.append((tool_name, site))
        raise PacketRequiredError("gate hit (spy)")

    monkeypatch.setattr(mutate, "require_approved_packet", spy)

    func = mutate.GUARDED_TOOLS[tool_name]
    with pytest.raises(PacketRequiredError):
        func(site="example", **APPLY_KWARGS[tool_name])

    assert calls == [(tool_name, "example")], f"{tool_name} did not call the shared guard exactly once"


@pytest.mark.parametrize("tool_name", sorted(mutate.GUARDED_TOOLS))
def test_guarded_tool_blocks_without_approved_packet(tool_name, wired):
    # End-to-end: with no approved packet present, apply=True must raise.
    func = mutate.GUARDED_TOOLS[tool_name]
    with pytest.raises(PacketRequiredError):
        func(site="example", **APPLY_KWARGS[tool_name])
