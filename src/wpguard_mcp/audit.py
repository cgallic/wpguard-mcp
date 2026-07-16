"""Read-only audit view over the packet + snapshot ledgers (issue #11).

The JSONL ledgers are the source of truth but are unpleasant to review by
grepping files. This is a small `wpguard audit` CLI that renders open/closed
packets, their snapshots, and verify status as a readable timeline. It is a
*view* over the existing JSONL -- no new storage engine, no writes.

    wpguard audit                       # everything
    wpguard audit --site example.com    # one site
    wpguard audit --since 7d            # opened in the last 7 days
    wpguard audit --status approved     # only approved packets
    wpguard audit --json                # machine-readable

Time windows: --since accepts Nd / Nh / Nm / Ns (days/hours/minutes/seconds).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone

from .guard import PacketStore, SnapshotStore, get_packet_store, get_snapshot_store

_SINCE_RE = re.compile(r"^(\d+)\s*([dhms])$")
_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


class InvalidSinceError(ValueError):
    pass


def parse_since(value: str) -> timedelta:
    match = _SINCE_RE.match(value.strip().lower())
    if not match:
        raise InvalidSinceError(f"invalid --since '{value}'; expected forms like 7d, 24h, 30m, 90s")
    amount, unit = int(match.group(1)), match.group(2)
    return timedelta(seconds=amount * _UNIT_SECONDS[unit])


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def build_report(
    packet_store: PacketStore,
    snapshot_store: SnapshotStore,
    site: str | None = None,
    since: timedelta | None = None,
    status: str | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Return a list of packet records (newest first), each with its snapshots."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - since if since is not None else None

    packets = packet_store.list_packets(site=site, status=status)
    report: list[dict] = []
    for packet in packets:
        if cutoff is not None and _parse_iso(packet.opened_at) < cutoff:
            continue
        snapshots = snapshot_store.list_for_packet(packet.id)
        record = packet.to_dict()
        record["snapshots"] = [s.to_dict() for s in snapshots]
        report.append(record)

    report.sort(key=lambda r: r["opened_at"], reverse=True)
    return report


def render_text(report: list[dict]) -> str:
    if not report:
        return "No packets match.\n"
    lines: list[str] = []
    for r in report:
        state = r["status"].upper()
        opened = r["opened_at"]
        header = f"[{state}] {r['id']}  {r['site']}  target={r.get('target', '*')}  risk={r['risk']}  opened={opened}"
        lines.append(header)
        lines.append(f"    summary : {r['summary']}")
        if r.get("approver"):
            lines.append(f"    approved: {r['approver']} @ {r.get('approved_at')}")
        if r.get("closed_at"):
            lines.append(f"    closed  : {r.get('outcome') or '(no outcome)'} @ {r['closed_at']}")
        for snap in r.get("snapshots", []):
            prev = _truncate(snap.get("previous_value"))
            new = _truncate(snap.get("new_value"))
            lines.append(f"    change  : {snap['tool']} {snap['target']}: {prev!r} -> {new!r}")
        for entry in r.get("log", []):
            lines.append(f"    log     : {entry.get('at')} {entry.get('message')}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _truncate(value, limit: int = 60) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wpguard", description="wpguard-mcp local tools")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", help="Review the change-packet audit trail")
    audit_p.add_argument("--site", default=None, help="Filter to one site")
    audit_p.add_argument("--since", default=None, help="Only packets opened within this window (e.g. 7d, 24h)")
    audit_p.add_argument(
        "--status", default=None, choices=["proposed", "approved", "closed"], help="Filter by packet status"
    )
    audit_p.add_argument("--json", action="store_true", help="Emit JSON instead of a text timeline")

    args = parser.parse_args(argv)

    if args.command == "audit":
        try:
            since = parse_since(args.since) if args.since else None
        except InvalidSinceError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        report = build_report(
            get_packet_store(), get_snapshot_store(), site=args.site, since=since, status=args.status
        )
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(render_text(report), end="")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
