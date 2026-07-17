from __future__ import annotations

from wpguard_mcp.cloud import CloudConfig, load_cloud_config, pair_instance, poll_decisions
from wpguard_mcp.guard import PacketStore


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_pair_persists_instance_token(tmp_path, monkeypatch):
    path = tmp_path / "cloud.json"
    monkeypatch.setattr(
        "wpguard_mcp.cloud.httpx.post",
        lambda *args, **kwargs: FakeResponse({"instanceId": "ins_1", "token": "secret"}),
    )
    config = pair_instance("PAIRCODE", "agency-box", url="https://cloud.example", path=path)
    assert config.instance_id == "ins_1"
    assert load_cloud_config(path) == config


def test_poll_applies_approval_to_matching_local_packet(tmp_path, monkeypatch):
    store = PacketStore(tmp_path / "packets.jsonl")
    packet = store.open_packet("example.com", "Update title", target="option:blogname")
    monkeypatch.setattr(
        "wpguard_mcp.cloud.httpx.get",
        lambda *args, **kwargs: FakeResponse(
            {
                "decisions": [
                    {
                        "decision": "approved",
                        "localPacketId": packet.id,
                        "approver": "owner@example.com",
                        "packetDigest": "abc",
                    }
                ]
            }
        ),
    )
    config = CloudConfig("https://cloud.example", "ins_1", "secret", "agency-box")
    results = poll_decisions(config=config, store=store)
    assert results[0]["applied"] is True
    assert store.get(packet.id).is_approved
    assert store.get(packet.id).approver == "cloud:owner@example.com"


def test_poll_reports_unknown_packet_without_mutation(tmp_path, monkeypatch):
    store = PacketStore(tmp_path / "packets.jsonl")
    monkeypatch.setattr(
        "wpguard_mcp.cloud.httpx.get",
        lambda *args, **kwargs: FakeResponse(
            {"decisions": [{"decision": "approved", "localPacketId": "missing", "approver": "x"}]}
        ),
    )
    config = CloudConfig("https://cloud.example", "ins_1", "secret", "agency-box")
    results = poll_decisions(config=config, store=store)
    assert results[0]["applied"] is False
    assert results[0]["reason"] == "local packet not found"
