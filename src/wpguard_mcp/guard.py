"""Change-guard: packet store, snapshot store, and the guard check itself.

A "change packet" is a lightweight audit record that must exist -- and be
*approved* -- before any mutating tool is allowed to touch a live site: target
site, a one-line summary of intent, a risk level, and a timestamp. It answers
"why is this write happening, and who signed off on it" without requiring a
database or a ticketing system.

Packets move through three states:

    proposed  -- opened by whoever wants the change (packet_open)
    approved  -- authorized by packet_approve (a distinct step, so the
                 proposer and the approver can be different actors)
    closed    -- the change is done and accounted for (packet_close)

Only an *approved* (and still-open) packet satisfies the guard for an
`apply=True` write. This is the single shared gate every Tier 2/3 tool funnels
through (`require_approved_packet`) -- no tool implements its own inline check,
so a new tool added later cannot accidentally skip the gate.

While a packet is open it also holds a lightweight per-target lock (site +
resource), so two agents pointed at the same site can't silently race a
mutation against the same target. Locks auto-expire after a TTL so a crashed
session never blocks a target forever.

A "snapshot" is the previous value captured immediately before a guarded
write, so a human (or another tool call) can always answer "what did this
overwrite, and how do I put it back." Snapshots also record the value that was
written and how to re-read it, which powers the optional durable re-verify on
packet_close.

Both packets and snapshots are stored as append-only JSON-lines ledgers under
WPGUARD_STATE_DIR. That's a deliberate v1 simplification -- good enough for a
single operator or a single server process; not a concurrent multi-writer
database.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.environ.get("WPGUARD_STATE_DIR", "state"))
DEFAULT_PACKET_STORE_PATH = STATE_DIR / "packets" / "packets.jsonl"
DEFAULT_SNAPSHOT_STORE_PATH = STATE_DIR / "packets" / "snapshots.jsonl"

BYPASS_ENV_VAR = "WPGUARD_BYPASS_GUARD"
LOCK_TTL_ENV_VAR = "WPGUARD_LOCK_TTL_SECONDS"
DEFAULT_LOCK_TTL_SECONDS = 3600

WILDCARD_TARGET = "*"

# Packet lifecycle states.
STATUS_PROPOSED = "proposed"
STATUS_APPROVED = "approved"
STATUS_CLOSED = "closed"


class PacketRequiredError(RuntimeError):
    """Raised when a mutating tool is called without a matching *approved* change packet."""


class PacketNotFoundError(RuntimeError):
    """Raised when an operation references a packet id that doesn't exist."""


class PacketAlreadyClosedError(RuntimeError):
    """Raised when trying to approve, log to, or close an already-closed packet."""


class PacketStateError(RuntimeError):
    """Raised on an illegal state transition (e.g. approving a closed packet)."""


class TargetLockedError(RuntimeError):
    """Raised when packet_open would race an already-open packet on the same target."""


class ConflictError(RuntimeError):
    """Raised on an optimistic-concurrency conflict: the live value changed since dry-run.

    Carries the etag the caller presented and the etag the live value now
    hashes to, so the caller can re-preview against current state.
    """

    def __init__(self, message: str, expected_etag: str, actual_etag: str):
        super().__init__(message)
        self.expected_etag = expected_etag
        self.actual_etag = actual_etag


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def lock_ttl_seconds() -> int:
    raw = os.environ.get(LOCK_TTL_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_LOCK_TTL_SECONDS
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_LOCK_TTL_SECONDS


def _targets_overlap(a: str, b: str) -> bool:
    """Two lock targets conflict if they're identical or either is the whole-site wildcard."""
    return a == b or a == WILDCARD_TARGET or b == WILDCARD_TARGET


# --------------------------------------------------------------------------
# Change packets
# --------------------------------------------------------------------------


@dataclass
class ChangePacket:
    id: str
    site: str
    summary: str
    risk: str = "low"
    target: str = WILDCARD_TARGET
    status: str = STATUS_PROPOSED
    approver: str | None = None
    opened_at: str = field(default_factory=_now)
    approved_at: str | None = None
    closed_at: str | None = None
    outcome: str | None = None
    log: list = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    @property
    def is_approved(self) -> bool:
        return self.status == STATUS_APPROVED and self.is_open

    def lock_expires_at(self, ttl_seconds: int) -> datetime:
        return _parse_iso(self.opened_at) + _timedelta(ttl_seconds)

    def lock_is_live(self, ttl_seconds: int, now: datetime | None = None) -> bool:
        """A packet holds a live lock while it is open and within its TTL window."""
        if not self.is_open:
            return False
        now = now or datetime.now(timezone.utc)
        return now < self.lock_expires_at(ttl_seconds)

    def to_dict(self) -> dict:
        return asdict(self)


def _timedelta(seconds: int):
    from datetime import timedelta

    return timedelta(seconds=seconds)


class PacketStore:
    """Append-only JSON-lines packet ledger.

    Every open/approve/log/close call appends one event line to the ledger
    file. Current state is derived in-memory by replaying events on load, and
    kept in sync as operations happen.
    """

    def __init__(self, path: Path | str = DEFAULT_PACKET_STORE_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._packets: dict[str, ChangePacket] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                self._apply(json.loads(line))

    def _apply(self, event: dict) -> None:
        kind = event["event"]
        if kind == "open":
            packet = ChangePacket(
                id=event["id"],
                site=event["site"],
                summary=event["summary"],
                risk=event.get("risk", "low"),
                target=event.get("target", WILDCARD_TARGET),
                status=STATUS_PROPOSED,
                opened_at=event.get("opened_at", _now()),
            )
            self._packets[packet.id] = packet
        elif kind == "approve":
            existing = self._packets.get(event["id"])
            if existing is not None:
                existing.status = STATUS_APPROVED
                existing.approver = event.get("approver")
                existing.approved_at = event.get("approved_at", _now())
        elif kind == "log":
            existing = self._packets.get(event["id"])
            if existing is not None:
                existing.log.append({"at": event.get("at", _now()), "message": event["message"]})
        elif kind == "close":
            existing = self._packets.get(event["id"])
            if existing is not None:
                existing.closed_at = event.get("closed_at", _now())
                existing.status = STATUS_CLOSED
                existing.outcome = event.get("outcome")

    def _append(self, event: dict) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
        self._apply(event)

    def open_packet(
        self,
        site: str,
        summary: str,
        risk: str = "low",
        target: str = WILDCARD_TARGET,
    ) -> ChangePacket:
        """Open (propose) a packet, taking a per-target lock.

        Raises TargetLockedError if another open, non-expired packet already
        holds an overlapping lock on the same site+target.
        """
        conflict = self.find_locking_packet(site, target)
        if conflict is not None:
            raise TargetLockedError(
                f"target '{site}:{target}' is already in progress by packet {conflict.id} "
                f"(opened {conflict.opened_at}). Close it, or wait for its lock to expire, "
                f"before opening another packet on the same target."
            )
        packet_id = uuid.uuid4().hex[:12]
        self._append(
            {
                "event": "open",
                "id": packet_id,
                "site": site,
                "summary": summary,
                "risk": risk,
                "target": target,
                "opened_at": _now(),
            }
        )
        return self._packets[packet_id]

    def approve_packet(self, packet_id: str, approver: str) -> ChangePacket:
        packet = self._require(packet_id)
        if not packet.is_open:
            raise PacketAlreadyClosedError(f"packet {packet_id} is already closed; cannot approve")
        if packet.status == STATUS_APPROVED:
            return packet  # idempotent -- re-approving an approved packet is a no-op
        self._append(
            {"event": "approve", "id": packet_id, "approver": approver, "approved_at": _now()}
        )
        return self._packets[packet_id]

    def log(self, packet_id: str, message: str) -> ChangePacket:
        packet = self._require(packet_id)
        if not packet.is_open:
            raise PacketAlreadyClosedError(f"packet {packet_id} is already closed")
        self._append({"event": "log", "id": packet_id, "message": message, "at": _now()})
        return self._packets[packet_id]

    def close_packet(self, packet_id: str, outcome: str = "") -> ChangePacket:
        packet = self._require(packet_id)
        if not packet.is_open:
            raise PacketAlreadyClosedError(f"packet {packet_id} is already closed")
        self._append({"event": "close", "id": packet_id, "outcome": outcome, "closed_at": _now()})
        return self._packets[packet_id]

    def _require(self, packet_id: str) -> ChangePacket:
        packet = self._packets.get(packet_id)
        if packet is None:
            raise PacketNotFoundError(f"no packet with id '{packet_id}'")
        return packet

    def get(self, packet_id: str) -> ChangePacket | None:
        return self._packets.get(packet_id)

    def find_locking_packet(self, site: str, target: str) -> ChangePacket | None:
        """Return an open, non-expired packet whose lock overlaps site+target, if any."""
        ttl = lock_ttl_seconds()
        for packet in self._packets.values():
            if packet.site != site:
                continue
            if not packet.lock_is_live(ttl):
                continue
            if _targets_overlap(packet.target, target):
                return packet
        return None

    def get_open_packet(self, site: str) -> ChangePacket | None:
        """Return the most recently opened, still-open packet for `site`, if any.

        Note: "open" here means not-yet-closed regardless of approval state.
        Use `get_approved_open_packet` for the guard check.
        """
        candidates = [p for p in self._packets.values() if p.site == site and p.is_open]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.opened_at)

    def get_approved_open_packet(self, site: str) -> ChangePacket | None:
        """Return the most recently opened, still-open, *approved* packet for `site`."""
        candidates = [p for p in self._packets.values() if p.site == site and p.is_approved]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.opened_at)

    def list_packets(
        self,
        site: str | None = None,
        open_only: bool = False,
        status: str | None = None,
    ) -> list[ChangePacket]:
        packets = list(self._packets.values())
        if site is not None:
            packets = [p for p in packets if p.site == site]
        if open_only:
            packets = [p for p in packets if p.is_open]
        if status is not None:
            packets = [p for p in packets if p.status == status]
        return sorted(packets, key=lambda p: p.opened_at)


def bypass_enabled() -> bool:
    return os.environ.get(BYPASS_ENV_VAR, "").strip().lower() in ("1", "true", "yes")


def require_approved_packet(store: PacketStore, site: str) -> ChangePacket:
    """The single shared guard gate for every Tier 2/3 write.

    Raises PacketRequiredError unless an *approved*, still-open packet exists
    for `site`. Every mutating tool funnels through this one function rather
    than implementing its own inline packet check -- that is what makes it
    structurally impossible to add a new guarded tool that forgets the gate.

    Respects WPGUARD_BYPASS_GUARD=1 as a documented escape valve. The env var
    is a single global switch, not a per-tool allowance -- it is meant only
    for local development against a throwaway install, and is loud in the
    README about being dangerous if left on.
    """
    packet = store.get_approved_open_packet(site)
    if packet is not None:
        return packet
    if bypass_enabled():
        return ChangePacket(
            id="bypass",
            site=site,
            summary="GUARD BYPASSED via WPGUARD_BYPASS_GUARD",
            risk="unknown",
            status=STATUS_APPROVED,
        )
    # Distinguish "proposed but not approved" from "no packet at all" so the
    # caller gets an actionable message.
    open_but_unapproved = store.get_open_packet(site)
    if open_but_unapproved is not None:
        raise PacketRequiredError(
            f"packet {open_but_unapproved.id} for site '{site}' is still '{open_but_unapproved.status}', "
            f"not approved. Call packet_approve(packet_id=\"{open_but_unapproved.id}\", approver=\"...\") "
            f"before apply=True will run."
        )
    raise PacketRequiredError(
        f"No approved change packet for site '{site}'. Call packet_open(site=\"{site}\", ...) then "
        f"packet_approve(...) first, or set {BYPASS_ENV_VAR}=1 to bypass (dangerous; dev only)."
    )


# Backwards-compatible alias: the old name gated on an *open* packet; the guard
# now requires approval. Kept so external callers importing the old symbol keep
# working, but it delegates to the approval-gated check.
require_open_packet = require_approved_packet


# --------------------------------------------------------------------------
# Snapshots (previous-value capture for rollback + durable re-verify)
# --------------------------------------------------------------------------


@dataclass
class Snapshot:
    id: str
    packet_id: str
    site: str
    tool: str
    target: str
    previous_value: Any
    new_value: Any = None
    # How to re-read the mutated value later (for the optional durable check on
    # packet_close): a [kind, *args] spec, e.g. ["option", "blogname"] or
    # ["post_meta", 12, "_thumbnail_id"] or ["post_content", 12]. None means
    # "no clean re-read available" (e.g. raw wp_eval).
    reread: list | None = None
    taken_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)


class SnapshotStore:
    """Append-only JSON-lines ledger of pre-write snapshots, keyed by packet."""

    def __init__(self, path: Path | str = DEFAULT_SNAPSHOT_STORE_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        packet_id: str,
        site: str,
        tool: str,
        target: str,
        previous_value: Any,
        new_value: Any = None,
        reread: list | None = None,
    ) -> Snapshot:
        snapshot = Snapshot(
            id=uuid.uuid4().hex[:12],
            packet_id=packet_id,
            site=site,
            tool=tool,
            target=target,
            previous_value=previous_value,
            new_value=new_value,
            reread=reread,
        )
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snapshot.to_dict()) + "\n")
        return snapshot

    def list_for_packet(self, packet_id: str) -> list[Snapshot]:
        if not self.path.exists():
            return []
        results: list[Snapshot] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("packet_id") == packet_id:
                    results.append(Snapshot(**data))
        return results


# --------------------------------------------------------------------------
# Process-wide singletons (lazy; tests should construct PacketStore/
# SnapshotStore directly against a tmp path instead of using these)
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_packet_store() -> PacketStore:
    return PacketStore()


@lru_cache(maxsize=1)
def get_snapshot_store() -> SnapshotStore:
    return SnapshotStore()
