"""Explicit policies for narrowly pre-approved unattended changes."""

from __future__ import annotations

import fnmatch
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PreapprovalPolicy:
    id: str
    name: str
    site: str
    source: str
    verbs: list[str]
    target_pattern: str
    max_risk: str
    approver: str
    active: bool = True
    created_at: str = field(default_factory=_now)
    retired_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class PreapprovalStore:
    def __init__(self, path: Path | str | None = None):
        state = Path(os.environ.get("WPGUARD_STATE_DIR", "state"))
        self.path = Path(path or state / "policies" / "preapprovals.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _events(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]

    def _append(self, event: dict) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

    def list(self, active_only: bool = False) -> list[PreapprovalPolicy]:
        policies: dict[str, PreapprovalPolicy] = {}
        for event in self._events():
            if event["event"] == "create":
                policies[event["policy"]["id"]] = PreapprovalPolicy(**event["policy"])
            elif event["event"] == "retire" and event["id"] in policies:
                policies[event["id"]].active = False
                policies[event["id"]].retired_at = event["retired_at"]
        values = sorted(policies.values(), key=lambda policy: policy.created_at)
        return [policy for policy in values if policy.active] if active_only else values

    def create(self, **kwargs) -> PreapprovalPolicy:
        policy = PreapprovalPolicy(id=uuid.uuid4().hex[:12], **kwargs)
        self._append({"event": "create", "policy": policy.to_dict()})
        return policy

    def retire(self, policy_id: str) -> PreapprovalPolicy:
        policy = next((item for item in self.list() if item.id == policy_id), None)
        if policy is None:
            raise ValueError(f"no preapproval policy with id '{policy_id}'")
        if policy.active:
            self._append({"event": "retire", "id": policy_id, "retired_at": _now()})
        return next(item for item in self.list() if item.id == policy_id)

    def match(self, *, site: str, source: str, verb: str, target: str, risk: str) -> PreapprovalPolicy | None:
        levels = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        requested = levels.get(risk.lower(), 99)
        for policy in self.list(active_only=True):
            maximum = levels.get(policy.max_risk.lower(), -1)
            if (
                policy.site == site
                and policy.source == source
                and verb in policy.verbs
                and fnmatch.fnmatchcase(target, policy.target_pattern)
                and requested <= maximum
            ):
                return policy
        return None


@lru_cache(maxsize=1)
def get_preapproval_store() -> PreapprovalStore:
    return PreapprovalStore()
