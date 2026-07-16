"""Optional, best-effort outbound event hooks.

Two independent, entirely opt-in integrations share one emission point
(`emit_event`), and both are strictly fire-and-forget: a delivery failure
(network error, endpoint down, bad config) NEVER blocks or fails the local
operation that triggered it. The local JSONL ledger remains the single source
of truth regardless of whether anything is listening.

1. Cloud-reporting hook (issue #19)
   ----------------------------------
   If WPGUARD_CLOUD_REPORT_URL is set, every packet-lifecycle event is POSTed
   to it (with an optional bearer WPGUARD_CLOUD_API_KEY). This is the only
   piece of the open-source core that a hosted control plane (wpguard-cloud)
   consumes; the core stays completely useful with it unset. The payload is a
   thin metadata envelope defined below -- packet id/site/target/summary/risk/
   status/timestamp plus lightweight snapshot metadata, never site credentials
   and never full mutated content.

2. Notification webhook (issue #21)
   --------------------------------
   If WPGUARD_NOTIFY_WEBHOOKS is set (comma-separated URLs), selected events
   are POSTed as a human-readable message. Slack incoming-webhook and Discord
   webhook endpoints both accept a plain JSON POST, so the body carries both
   `text` (Slack) and `content` (Discord) keys and needs no per-provider
   special-casing. Which events fire is controlled by WPGUARD_NOTIFY_EVENTS
   (comma-separated); `tier3_eval_fired` always notifies regardless, since raw
   eval is the highest-risk action and should never be silent.

Nothing here imports anything commercial, account-aware, or billing-aware --
it is a dumb, optional POST.
"""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger("wpguard.notify")

CLOUD_URL_ENV = "WPGUARD_CLOUD_REPORT_URL"
CLOUD_KEY_ENV = "WPGUARD_CLOUD_API_KEY"
NOTIFY_WEBHOOKS_ENV = "WPGUARD_NOTIFY_WEBHOOKS"
NOTIFY_EVENTS_ENV = "WPGUARD_NOTIFY_EVENTS"

# Events the cloud hook always reports (the full packet lifecycle).
LIFECYCLE_EVENTS = {
    "packet_proposed",
    "packet_approved",
    "packet_closed",
    "packet_verify_failed",
    "tier3_eval_fired",
}

# Default set of events a human wants to be pinged about, if WPGUARD_NOTIFY_EVENTS
# is unset. Raw eval and verify failures are the ones you never want silent.
DEFAULT_NOTIFY_EVENTS = {"packet_proposed", "packet_verify_failed", "tier3_eval_fired"}

# tier3_eval_fired always notifies, even if excluded from WPGUARD_NOTIFY_EVENTS.
ALWAYS_NOTIFY_EVENTS = {"tier3_eval_fired"}

_DEFAULT_TIMEOUT = 5.0


@dataclass
class Delivery:
    url: str
    payload: dict
    headers: dict


# Test seam: set to a callable(list[Delivery]) to capture deliveries instead of
# firing real HTTP. Left None in production so emit_event does real POSTs.
_sink: Callable[[list], None] | None = None


def set_sink(sink: Callable[[list], None] | None) -> None:
    """Install (or clear, with None) a delivery sink -- used by tests to assert
    what would be sent without making network calls.
    """
    global _sink
    _sink = sink


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _notify_events() -> set:
    raw = os.environ.get(NOTIFY_EVENTS_ENV, "").strip()
    configured = set(_split_csv(raw)) if raw else set(DEFAULT_NOTIFY_EVENTS)
    return configured | ALWAYS_NOTIFY_EVENTS


def _cloud_payload(event: str, packet: dict) -> dict:
    """The public event contract wpguard-cloud consumes. Metadata only."""
    snapshot_meta = None
    if "durable_check" in packet:
        dc = packet["durable_check"]
        snapshot_meta = {"durable": dc.get("durable"), "checks": len(dc.get("checks", []))}
    return {
        "event": event,
        "timestamp": _now(),
        "packet_id": packet.get("id"),
        "site": packet.get("site"),
        "target": packet.get("target"),
        "summary": packet.get("summary"),
        "risk": packet.get("risk"),
        "status": packet.get("status"),
        "approver": packet.get("approver"),
        "opened_at": packet.get("opened_at"),
        "closed_at": packet.get("closed_at"),
        "outcome": packet.get("outcome"),
        "snapshot_meta": snapshot_meta,
    }


def _notify_message(event: str, packet: dict) -> str:
    """A one-line, act-on-it-without-a-dashboard message for a webhook."""
    site = packet.get("site", "?")
    target = packet.get("target", "*")
    summary = packet.get("summary", "")
    risk = packet.get("risk", "?")
    pid = packet.get("id", "?")
    label = {
        "packet_proposed": "🕓 Change proposed (needs approval)",
        "packet_approved": "✅ Change approved",
        "packet_closed": "☑️ Packet closed",
        "packet_verify_failed": "⚠️ Durable verify FAILED",
        "tier3_eval_fired": "🚨 Tier 3 raw eval fired",
    }.get(event, event)
    parts = [f"{label} — {site} [{target}] risk={risk}", f"“{summary}”", f"packet {pid}"]
    if packet.get("approver"):
        parts.append(f"approver={packet['approver']}")
    if packet.get("outcome"):
        parts.append(f"outcome={packet['outcome']}")
    return " · ".join(p for p in parts if p)


def _build_deliveries(event: str, packet: dict) -> list:
    deliveries: list[Delivery] = []

    cloud_url = os.environ.get(CLOUD_URL_ENV, "").strip()
    if cloud_url and event in LIFECYCLE_EVENTS:
        headers = {"Content-Type": "application/json"}
        key = os.environ.get(CLOUD_KEY_ENV, "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        deliveries.append(Delivery(url=cloud_url, payload=_cloud_payload(event, packet), headers=headers))

    webhooks = _split_csv(os.environ.get(NOTIFY_WEBHOOKS_ENV, ""))
    if webhooks and event in _notify_events():
        message = _notify_message(event, packet)
        body = {"text": message, "content": message}
        for url in webhooks:
            deliveries.append(Delivery(url=url, payload=body, headers={"Content-Type": "application/json"}))

    return deliveries


def _http_post(delivery: Delivery) -> None:
    try:
        import httpx

        httpx.post(delivery.url, json=delivery.payload, headers=delivery.headers, timeout=_DEFAULT_TIMEOUT)
    except Exception as exc:  # best-effort: never propagate
        logger.warning("wpguard notify delivery to %s failed: %s", delivery.url, exc)


def emit_event(event: str, packet: dict) -> None:
    """Fire optional cloud-report / notification deliveries for a packet event.

    Best-effort and non-blocking: builds the delivery list, then dispatches each
    on a daemon thread (or to the test sink). Any failure is logged and
    swallowed -- it must never affect the caller.
    """
    try:
        deliveries = _build_deliveries(event, packet)
    except Exception as exc:  # defensive: constructing a payload must not raise into the caller
        logger.warning("wpguard notify: failed to build deliveries for %s: %s", event, exc)
        return

    if not deliveries:
        return

    if _sink is not None:
        _sink(deliveries)
        return

    for delivery in deliveries:
        threading.Thread(target=_http_post, args=(delivery,), daemon=True).start()
