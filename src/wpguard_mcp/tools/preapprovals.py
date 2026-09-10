"""MCP tools for audited unattended-run approval policies."""

from __future__ import annotations

from ..guard import get_packet_store
from ..notify import emit_event
from ..preapproval import get_preapproval_store


def wp_preapproval_create(
    name: str,
    site: str,
    source: str,
    verbs: list[str],
    target_pattern: str,
    approver: str,
    max_risk: str = "low",
) -> dict:
    """Create an explicit policy for a narrow class of unattended changes."""
    if not name.strip() or not source.strip() or not approver.strip() or not verbs:
        raise ValueError("name, source, approver, and at least one verb are required")
    if "*" in verbs:
        raise ValueError("wildcard verbs are not allowed")
    if max_risk.lower() not in {"low", "medium", "high", "critical"}:
        raise ValueError("max_risk must be one of: low, medium, high, critical")
    if not site.strip() or not target_pattern.strip():
        raise ValueError("site and target_pattern are required")
    policy = get_preapproval_store().create(
        name=name.strip(),
        site=site,
        source=source.strip(),
        verbs=sorted(set(verbs)),
        target_pattern=target_pattern,
        max_risk=max_risk.lower(),
        approver=approver.strip(),
    )
    emit_event("preapproval_created", policy.to_dict())
    return policy.to_dict()


def wp_preapproval_list(active_only: bool = True) -> list[dict]:
    """List unattended-run policies without exposing any credentials."""
    return [item.to_dict() for item in get_preapproval_store().list(active_only=active_only)]


def wp_preapproval_retire(policy_id: str) -> dict:
    """Retire a policy so it cannot authorize another unattended packet."""
    policy = get_preapproval_store().retire(policy_id)
    emit_event("preapproval_retired", policy.to_dict())
    return policy.to_dict()


def packet_open_preapproved(
    site: str,
    summary: str,
    source: str,
    target: str,
    verb: str,
    change_digest: str,
    risk: str = "low",
) -> dict:
    """Open and approve one exact packet only when an active policy matches it."""
    policy = get_preapproval_store().match(site=site, source=source, verb=verb, target=target, risk=risk)
    if policy is None:
        raise PermissionError("no active preapproval policy matches this site, source, verb, target, and risk")
    store = get_packet_store()
    packet = store.open_packet(
        site=site, summary=summary, risk=risk, target=target, verb=verb, change_digest=change_digest
    )
    packet = store.approve_packet(packet.id, approver=f"preapproval:{policy.id}:{policy.approver}")
    packet = store.log(packet.id, f"unattended source={source}; policy={policy.id}")
    result = packet.to_dict()
    result["unattended"] = True
    result["preapproval_policy_id"] = policy.id
    emit_event("packet_preapproved", result)
    return result
