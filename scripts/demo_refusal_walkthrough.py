#!/usr/bin/env python
"""Guarded-change refusal walkthrough -- REAL, reproducible proof of the
README's core safety claim: an unguarded write attempt is refused, and only
an approved change packet lets a write through.

This calls the actual installed wpguard_mcp package's tool functions
(src/wpguard_mcp/tools/mutate.py, packets.py, recon.py) in-process, against a
FAKE WordPress site -- no real SSH connection, no real WordPress install, no
network access. The fake is the same pattern tests/conftest.py's `wired`
fixture uses (patch each tool module's get_site_registry / get_packet_store /
get_snapshot_store, and patch transports.ssh_wpcli's run_wp_cli /
run_wp_cli_json / run_eval), reimplemented here without pytest so it runs as
a plain script and produces a real, pasteable terminal transcript. It is
extended slightly beyond that test fixture (see build_fake_site() below) to
also answer wp_recon's reads and to make a fake write actually stick, since
this walkthrough also demos a confirm-read after the write -- neither of
which the existing test suite needed.

Run it with:

    .venv\\Scripts\\python.exe scripts\\demo_refusal_walkthrough.py

Every JSON blob this script prints is `json.dumps` of a real return value
from real wpguard_mcp code. Every "REFUSED" line is the real exception type
and message caught from a real raised exception -- nothing here is
hand-written fake terminal output. Re-running it produces fresh packet ids,
snapshot ids, and timestamps (see expect_refusal()'s assertions, which make
the script itself fail loudly if a step that's supposed to be refused ever
silently succeeds instead).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# --- Neutralize ambient config BEFORE importing wpguard_mcp, so this demo
# never depends on -- or accidentally touches -- real machine state: a real
# ./state dir, a paired WP MCP Cloud instance, notification webhooks, or the
# WPGUARD_BYPASS_GUARD dev escape hatch (which would defeat the entire point
# of this walkthrough). Every store this script uses is explicitly pointed at
# a fresh temp directory instead.
DEMO_STATE_DIR = Path(tempfile.mkdtemp(prefix="wpguard_demo_"))
os.environ["WPGUARD_STATE_DIR"] = str(DEMO_STATE_DIR)
for _var in ("WPGUARD_BYPASS_GUARD", "WPGUARD_CLOUD_REPORT_URL", "WPGUARD_CLOUD_API_KEY", "WPGUARD_NOTIFY_WEBHOOKS"):
    os.environ.pop(_var, None)

import wpguard_mcp  # noqa: E402
from wpguard_mcp.config import SiteConfig  # noqa: E402
from wpguard_mcp.guard import ConflictError, PacketRequiredError, PacketStore, SnapshotStore  # noqa: E402
from wpguard_mcp.tools import mutate, packets, recon  # noqa: E402
from wpguard_mcp.transports import ssh_wpcli  # noqa: E402


# ---------------------------------------------------------------------------
# Fake WordPress site + fake SSH transport.
# ---------------------------------------------------------------------------


class FakeRegistry:
    """Same shape as tests/conftest.py:FakeRegistry -- one fake site, handed
    back regardless of the name asked for.
    """

    def __init__(self, site: SiteConfig):
        self._site = site

    def get(self, name: str) -> SiteConfig:
        return self._site


FAKE_PLUGINS = [
    {"name": "akismet", "status": "active", "version": "5.3"},
    {"name": "yoast-seo", "status": "active", "version": "22.5"},
    {"name": "classic-editor", "status": "inactive", "version": "1.6.3"},
]
FAKE_THEMES = [
    {"name": "twentytwentyfour", "status": "active", "version": "1.2"},
]


def build_fake_site():
    """Build the fake site config, isolated packet/snapshot stores, and a fake
    SSH transport, then wire them into the mutate/packets/recon tool modules
    -- exactly the seams tests/conftest.py patches with pytest's `monkeypatch`,
    done here with plain attribute assignment since this script runs outside
    pytest. Returns (site, packet_store, snapshot_store, state).
    """
    site = SiteConfig(
        name="example-blog", transport="ssh", ssh_host="example-blog.example.com", ssh_user="deploy"
    )
    registry = FakeRegistry(site)
    packet_store = PacketStore(path=DEMO_STATE_DIR / "packets.jsonl")
    snapshot_store = SnapshotStore(path=DEMO_STATE_DIR / "snapshots.jsonl")

    mutate.get_site_registry = lambda: registry
    mutate.get_packet_store = lambda: packet_store
    mutate.get_snapshot_store = lambda: snapshot_store
    packets.get_site_registry = lambda: registry
    packets.get_packet_store = lambda: packet_store
    packets.get_snapshot_store = lambda: snapshot_store
    recon.get_site_registry = lambda: registry

    state = {"values": {}, "writes": [], "eval_calls": []}
    state["values"][("option", "blogname")] = "Example Blog (unchanged)"
    state["values"][("option", "blogdescription")] = "Just another WordPress site"
    state["values"][("option", "siteurl")] = "https://example-blog.example.com"

    def fake_run_wp_cli(site_config, args, timeout=60):
        if args[:2] == ["option", "get"]:
            return ssh_wpcli.CommandResult(0, state["values"].get(("option", args[2]), ""), "")
        if args[:2] == ["core", "version"]:
            return ssh_wpcli.CommandResult(0, "6.6.2", "")
        if args[:2] == ["option", "update"]:
            option_name, new_value = args[2], args[3]
            state["writes"].append(list(args))
            # Unlike tests/conftest.py's fixture (which deliberately leaves
            # post-write state to each test, since some simulate a write NOT
            # sticking), this demo's fake site behaves like a real one: a
            # write is immediately visible on the next read, so step 6's
            # confirm-read shows a real change.
            state["values"][("option", option_name)] = new_value
            return ssh_wpcli.CommandResult(0, f"Success: Updated '{option_name}' option.", "")
        # Anything this walkthrough doesn't exercise (post meta/content, cache
        # flush, ...): record as a write and move on.
        state["writes"].append(list(args))
        return ssh_wpcli.CommandResult(0, "", "")

    def fake_run_wp_cli_json(site_config, args, timeout=60):
        if args[:2] == ["plugin", "list"]:
            return FAKE_PLUGINS
        if args[:2] == ["theme", "list"]:
            return FAKE_THEMES
        return []

    def fake_run_eval(site_config, php_code, timeout=60):
        state["eval_calls"].append(php_code)
        return ssh_wpcli.CommandResult(0, "ok", "")

    ssh_wpcli.run_wp_cli = fake_run_wp_cli
    ssh_wpcli.run_wp_cli_json = fake_run_wp_cli_json
    ssh_wpcli.run_eval = fake_run_eval

    return site, packet_store, snapshot_store, state


# ---------------------------------------------------------------------------
# Transcript helpers. Nothing here fabricates output: show_result() only ever
# prints json.dumps() of a real return value, and expect_refusal() only ever
# prints the type/message of a real exception it actually caught.
# ---------------------------------------------------------------------------


def step(n, title):
    print()
    print(f"##### STEP {n}: {title}")
    print()


def show_call(call_text: str):
    print(f">>> {call_text}")


def show_result(result):
    print(json.dumps(result, indent=2, default=str))


def expect_refusal(exc_type, fn):
    """Call fn(); assert it raises exactly exc_type; print and return the
    exception. Raises AssertionError -- failing this script loudly -- if fn()
    either succeeds or raises the wrong exception type, so a "REFUSED" line
    in the transcript can only ever mean a real refusal really happened.
    """
    try:
        result = fn()
    except exc_type as exc:
        print(f"REFUSED ({exc_type.__name__}): {exc}")
        return exc
    else:
        raise AssertionError(
            f"expected {exc_type.__name__} to be raised, but the call SUCCEEDED and returned: {result!r}\n"
            "The guard did not refuse an apply=True call this demo expects to be refused."
        )


def main() -> None:
    print("=" * 78)
    print("wpguard-mcp -- guarded-change refusal walkthrough")
    print(f"generated (UTC): {datetime.now(timezone.utc).isoformat()}")
    print(f"python: {sys.version.split()[0]} ({sys.executable})")
    print(f"wpguard_mcp: {wpguard_mcp.__version__} ({wpguard_mcp.__file__})")
    print(f"demo state dir (fresh temp dir; never the repo's real ./state): {DEMO_STATE_DIR}")
    print("Site is FAKE: transport='ssh' but ssh_wpcli.run_wp_cli/run_wp_cli_json/run_eval are")
    print("monkeypatched to an in-memory fake -- no real SSH connection, no real WordPress site.")
    print("=" * 78)

    site, packet_store, snapshot_store, state = build_fake_site()

    # -- Step 1 --------------------------------------------------------
    step(1, "Recon a fake site -- succeeds, no packet required (Tier 1, read-only)")
    show_call('recon.wp_recon(site="example-blog")')
    recon_result = recon.wp_recon(site="example-blog")
    show_result(recon_result)
    assert recon_result["_wpguard"]["injection_flagged"] is False
    print(
        f"\nNo change packet was opened or consulted for this call -- packet_store has "
        f"{len(packet_store.list_packets())} packets so far. Tier 1 reads never touch the guard."
    )

    # -- Step 2 --------------------------------------------------------
    step(2, "Attempt an unapproved write: wp_mutate_option(apply=True), NO packet open at all")
    print("Simulating a reckless (or compromised) agent that skips straight to a write, with no")
    print("prior dry-run and no change packet of any kind -- exactly the case the guard exists")
    print("to hard-refuse.")
    show_call(
        'mutate.wp_mutate_option(site="example-blog", option_name="blogname", '
        'new_value="Reckless unapproved rename", apply=True)'
    )
    expect_refusal(
        PacketRequiredError,
        lambda: mutate.wp_mutate_option(
            site="example-blog", option_name="blogname", new_value="Reckless unapproved rename", apply=True
        ),
    )
    assert state["writes"] == [], "a write reached the fake site's transport -- the guard failed to block it"
    print(
        f"\nConfirmed: {len(state['writes'])} writes reached the fake site's transport. The refusal "
        "happened before wp-cli's `option update` was ever invoked."
    )

    # -- Step 3 --------------------------------------------------------
    step(3, "Preview the change (dry-run), then open a change packet bound to that exact preview")
    show_call(
        'mutate.wp_mutate_option(site="example-blog", option_name="blogname", new_value="Summer Sale HQ")'
    )
    preview = mutate.wp_mutate_option(site="example-blog", option_name="blogname", new_value="Summer Sale HQ")
    show_result(preview)
    assert preview["dry_run"] is True and preview["applied"] is False

    print()
    show_call(
        'packets.packet_open(site="example-blog", summary="Rename blog for summer promo", '
        'risk="low", target="option:blogname", verb="wp_mutate_option", '
        'change_digest=preview["change_digest"])'
    )
    packet = packets.packet_open(
        site="example-blog",
        summary="Rename blog for summer promo",
        risk="low",
        target="option:blogname",
        verb="wp_mutate_option",
        change_digest=preview["change_digest"],
    )
    show_result(packet)
    assert packet["status"] == "proposed"

    # -- Step 4 --------------------------------------------------------
    step(4, "Attempt apply=True again -- packet exists but is only PROPOSED, not approved: still refused")
    show_call(
        'mutate.wp_mutate_option(site="example-blog", option_name="blogname", new_value="Summer Sale HQ", '
        'apply=True, expected_etag=preview["etag"])'
    )
    expect_refusal(
        PacketRequiredError,
        lambda: mutate.wp_mutate_option(
            site="example-blog",
            option_name="blogname",
            new_value="Summer Sale HQ",
            apply=True,
            expected_etag=preview["etag"],
        ),
    )
    assert state["writes"] == []
    print(
        f"\nStill {len(state['writes'])} writes. An open-but-unapproved packet does not satisfy the "
        "guard -- propose and approve are deliberately two separate steps."
    )

    # -- Step 5 --------------------------------------------------------
    step(5, "Approve the packet")
    show_call(f'packets.packet_approve(packet_id="{packet["id"]}", approver="connor")')
    approved = packets.packet_approve(packet_id=packet["id"], approver="connor")
    show_result(approved)
    assert approved["status"] == "approved"

    # -- Step 6 --------------------------------------------------------
    step(6, "Apply again -- now succeeds: capture packet_id / snapshot_id, then confirm the write landed")
    show_call(
        'mutate.wp_mutate_option(site="example-blog", option_name="blogname", new_value="Summer Sale HQ", '
        'apply=True, expected_etag=preview["etag"])'
    )
    applied = mutate.wp_mutate_option(
        site="example-blog",
        option_name="blogname",
        new_value="Summer Sale HQ",
        apply=True,
        expected_etag=preview["etag"],
    )
    show_result(applied)
    assert applied["applied"] is True
    assert applied["packet_id"] == packet["id"]
    assert ["option", "update", "blogname", "Summer Sale HQ"] in state["writes"]
    print(f"\npacket_id   = {applied['packet_id']}")
    print(f"snapshot_id = {applied['snapshot_id']}")

    snaps = snapshot_store.list_for_packet(packet["id"])
    print(f"\n{len(snaps)} snapshot(s) recorded for this packet (previous -> new value):")
    for snap in snaps:
        print(f"  snapshot {snap.id}: {snap.target}: {snap.previous_value!r} -> {snap.new_value!r}")

    print()
    show_call('recon.wp_get_option(site="example-blog", option_name="blogname")  # confirm read-back')
    confirm = recon.wp_get_option(site="example-blog", option_name="blogname")
    show_result(confirm)
    assert confirm["value"]["untrusted_content"] == "Summer Sale HQ"
    print("\nThe live (fake) value now reads back as the approved new value -- the write really happened.")

    # -- Step 7 (bonus) --------------------------------------------------------
    step(7, "BONUS: stale-etag refusal -- someone else changes the value between dry-run and apply")
    print("Same propose/approve flow, on a different option (blogdescription) so it doesn't collide")
    print("with the still-open packet from steps 3-6. This time, something else changes the live")
    print("value AFTER the dry-run preview but BEFORE the (approved) apply -- e.g. another admin")
    print("editing it directly in wp-admin, or another agent's write landing in between.")

    show_call(
        'mutate.wp_mutate_option(site="example-blog", option_name="blogdescription", '
        'new_value="Autumn Sale -- 30% off everything")'
    )
    preview2 = mutate.wp_mutate_option(
        site="example-blog", option_name="blogdescription", new_value="Autumn Sale -- 30% off everything"
    )
    show_result(preview2)

    print()
    show_call(
        'packets.packet_open(site="example-blog", summary="Update tagline for autumn promo", '
        'risk="low", target="option:blogdescription", verb="wp_mutate_option", '
        'change_digest=preview2["change_digest"])'
    )
    packet2 = packets.packet_open(
        site="example-blog",
        summary="Update tagline for autumn promo",
        risk="low",
        target="option:blogdescription",
        verb="wp_mutate_option",
        change_digest=preview2["change_digest"],
    )
    show_result(packet2)

    print()
    show_call(f'packets.packet_approve(packet_id="{packet2["id"]}", approver="connor")')
    approved2 = packets.packet_approve(packet_id=packet2["id"], approver="connor")
    show_result(approved2)

    print()
    print(">>> SIMULATING an out-of-band change -- NOT made through wpguard-mcp at all")
    print("    (e.g. someone hand-edited it in wp-admin while this packet was pending):")
    print('    state["values"][("option", "blogdescription")] = "Changed by someone else entirely"')
    state["values"][("option", "blogdescription")] = "Changed by someone else entirely"

    print()
    show_call(
        'mutate.wp_mutate_option(site="example-blog", option_name="blogdescription", '
        'new_value="Autumn Sale -- 30% off everything", apply=True, '
        'expected_etag=preview2["etag"])  # etag is now STALE'
    )
    exc = expect_refusal(
        ConflictError,
        lambda: mutate.wp_mutate_option(
            site="example-blog",
            option_name="blogdescription",
            new_value="Autumn Sale -- 30% off everything",
            apply=True,
            expected_etag=preview2["etag"],
        ),
    )
    print(f"\nexpected_etag (from the now-stale dry-run): {exc.expected_etag}")
    print(f"actual_etag   (live value right now):        {exc.actual_etag}")
    assert ["option", "update", "blogdescription", "Autumn Sale -- 30% off everything"] not in state["writes"]
    print(
        "\nEven with an APPROVED packet in hand, the apply refuses: the packet authorizes the "
        "previewed\nchange against the previewed pre-change state, not a blind overwrite."
    )

    # -- Summary --------------------------------------------------------
    print()
    print("=" * 78)
    final_packets = packets.packet_list(site="example-blog")
    approved_count = sum(1 for p in final_packets if p["status"] == "approved")
    print(
        f"Done. {len(final_packets)} packet(s) opened this run, {approved_count} approved, "
        f"{len(state['writes'])} real write(s) reached the fake site's transport."
    )
    for p in final_packets:
        print(f"  packet {p['id']}  status={p['status']:<9}  target={p['target']:<24}  \"{p['summary']}\"")
    print(f"Demo state (packets.jsonl / snapshots.jsonl) is under: {DEMO_STATE_DIR}")
    print("=" * 78)


if __name__ == "__main__":
    main()
