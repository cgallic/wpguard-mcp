"""Pair and poll the optional WP MCP Cloud control plane.

Cloud coordinates approvals but never receives WordPress or SSH credentials.
The local instance makes every connection outbound and remains the enforcement
point for all writes.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from .guard import PacketStore, get_packet_store

STATE_DIR = Path(os.environ.get("WPGUARD_STATE_DIR", "state"))
CLOUD_CONFIG_PATH = STATE_DIR / "config" / "cloud.json"
CLOUD_URL_ENV = "WPGUARD_CLOUD_URL"
CLOUD_TOKEN_ENV = "WPGUARD_CLOUD_API_KEY"


@dataclass
class CloudConfig:
    url: str
    instance_id: str
    token: str
    instance_name: str

    def to_dict(self) -> dict:
        return asdict(self)


def load_cloud_config(path: Path | str = CLOUD_CONFIG_PATH) -> CloudConfig | None:
    config_path = Path(path)
    if not config_path.exists():
        return None
    return CloudConfig(**json.loads(config_path.read_text(encoding="utf-8")))


def save_cloud_config(config: CloudConfig, path: Path | str = CLOUD_CONFIG_PATH) -> None:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
    try:
        config_path.chmod(0o600)
    except OSError:
        pass


def pair_instance(code: str, name: str, url: str | None = None, path: Path | str = CLOUD_CONFIG_PATH) -> CloudConfig:
    base_url = (url or os.environ.get(CLOUD_URL_ENV, "https://api.wpmcp.io")).rstrip("/")
    response = httpx.post(
        f"{base_url}/api/v1/instances/pair",
        json={"code": code, "name": name},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    config = CloudConfig(
        url=base_url,
        instance_id=payload["instanceId"],
        token=payload["token"],
        instance_name=name,
    )
    save_cloud_config(config, path)
    return config


def poll_decisions(
    config: CloudConfig | None = None,
    store: PacketStore | None = None,
) -> list[dict]:
    config = config or load_cloud_config()
    if config is None:
        raise RuntimeError("WP MCP Cloud is not paired. Run `wpguard cloud pair --code ... --name ...` first.")
    store = store or get_packet_store()
    response = httpx.get(
        f"{config.url}/api/v1/decisions",
        headers={"Authorization": f"Bearer {config.token}"},
        timeout=15,
    )
    response.raise_for_status()
    results: list[dict] = []
    for decision in response.json().get("decisions", []):
        local_packet_id = decision.get("localPacketId")
        packet = store.get(local_packet_id) if local_packet_id else None
        if packet is None:
            results.append({**decision, "applied": False, "reason": "local packet not found"})
            continue
        if decision.get("decision") == "approved":
            store.approve_packet(local_packet_id, approver=f"cloud:{decision.get('approver', 'unknown')}")
            results.append({**decision, "applied": True})
        else:
            store.log(local_packet_id, f"Cloud rejected by {decision.get('approver')}: {decision.get('comment') or ''}")
            results.append({**decision, "applied": True})
    return results
