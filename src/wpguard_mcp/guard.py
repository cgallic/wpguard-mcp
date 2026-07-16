"""Change-guard: packet store, snapshot store, and the guard check itself.

A "change packet" is a lightweight audit record that must be open before any
mutating tool is allowed to touch a live site: target site, a one-line
summary of intent, a risk level, and a timestamp. It answers "why is this
write happening" without requiring a database or a ticketing system.

A "snapshot" is the previous value captured immediately before a guarded
write, so a human (or another tool call) can always answer "what did this
overwrite, and how do I put it back."

Both are stored as append-only JSON-lines ledgers under WPGUARD_STATE_DIR.
That's a deliberate v1 simplification -- good enough for a single operator
or a single server process; not a concurrent multi-writer database.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

STATE_DIR = Path(os.environ.get("WPGUARD_STATE_DIR", "state"))
DEFAULT_PACKET_STORE_PATH = STATE_DIR / "packets" / "packets.jsonl"
DEFAULT_SNAPSHOT_STORE_PATH = STATE_DIR / "packets" / "snapshots.jsonl"

BYPASS_ENV_VAR = "WPGUARD_BYPASS_GUARD"


class PacketRequiredError(RuntimeError):
    """Raised when a mutating tool is called without a matching open change packet."""


class PacketNotFoundError(RuntimeError):
    """Raised when an operation references a packet id that doesn't exist."""


class PacketAlreadyClosedError(RuntimeError):
    """Raised when trying to log to, or close, an already-closed packet."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Change packets
# --------------------------------------------------------------------------


@dataclass
class ChangePacket:
    id: str
    site: str
    summary: str
    risk: str = "low"
    opened_at: str = field(default_factory=_now)
    closed_at: Optional[str] = None
    outcome: Optional[str] = None
    log: list = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    def to_dict(self) -> dict:
        return asdict(self)


class PacketStore:
    """Append-only JSON-lines packet ledger.

    Every open/log/close call appends one event line to the ledger file.
    Current state is derived in-memory by replaying events on load, and kept
    in sync as operations happen.
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
                opened_at=event.get("opened_at", _now()),
            )
            self._packets[packet.id] = packet
        elif kind == "log":
            packet = self._packets.get(event["id"])
            if packet is not None:
                packet.log.append({"at": event.get("at", _now()), "message": event["message"]})
        elif kind == "close":
            packet = self._packets.get(event["id"])
            if packet is not None:
                packet.closed_at = event.get("closed_at", _now())
                packet.outcome = event.get("outcome")

    def _append(self, event: dict) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
        self._apply(event)

    def open_packet(self, site: str, summary: str, risk: str = "low") -> ChangePacket:
        packet_id = uuid.uuid4().hex[:12]
        self._append(
            {
                "event": "open",
                "id": packet_id,
                "site": site,
                "summary": summary,
                "risk": risk,
                "opened_at": _now(),
            }
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

    def get(self, packet_id: str) -> Optional[ChangePacket]:
        return self._packets.get(packet_id)

    def get_open_packet(self, site: str) -> Optional[ChangePacket]:
        """Return the most recently opened, still-open packet for `site`, if any."""
        candidates = [p for p in self._packets.values() if p.site == site and p.is_open]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.opened_at)

    def list_packets(self, site: Optional[str] = None, open_only: bool = False) -> list[ChangePacket]:
        packets = list(self._packets.values())
        if site is not None:
            packets = [p for p in packets if p.site == site]
        if open_only:
            packets = [p for p in packets if p.is_open]
        return sorted(packets, key=lambda p: p.opened_at)


def bypass_enabled() -> bool:
    return os.environ.get(BYPASS_ENV_VAR, "").strip().lower() in ("1", "true", "yes")


def require_open_packet(store: PacketStore, site: str) -> ChangePacket:
    """Guard check: raise PacketRequiredError unless an open packet exists for `site`.

    Respects WPGUARD_BYPASS_GUARD=1 as a documented escape valve. The env var
    is a single global switch, not a per-tool allowance -- it is meant only
    for non-mutating diagnostic calls, and is loud in the README about being
    dangerous if left on.
    """
    packet = store.get_open_packet(site)
    if packet is not None:
        return packet
    if bypass_enabled():
        return ChangePacket(id="bypass", site=site, summary="GUARD BYPASSED via WPGUARD_BYPASS_GUARD", risk="unknown")
    raise PacketRequiredError(
        f"No open change packet for site '{site}'. Call packet_open(site=\"{site}\", ...) "
        f"first, or set {BYPASS_ENV_VAR}=1 to bypass (dangerous; non-mutating calls only)."
    )


# --------------------------------------------------------------------------
# Snapshots (previous-value capture for rollback)
# --------------------------------------------------------------------------


@dataclass
class Snapshot:
    id: str
    packet_id: str
    site: str
    tool: str
    target: str
    previous_value: Any
    taken_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)


class SnapshotStore:
    """Append-only JSON-lines ledger of pre-write snapshots, keyed by packet."""

    def __init__(self, path: Path | str = DEFAULT_SNAPSHOT_STORE_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, packet_id: str, site: str, tool: str, target: str, previous_value: Any) -> Snapshot:
        snapshot = Snapshot(
            id=uuid.uuid4().hex[:12],
            packet_id=packet_id,
            site=site,
            tool=tool,
            target=target,
            previous_value=previous_value,
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
