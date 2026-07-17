"""Issues #19 / #21: optional cloud-reporting hook and notification webhooks.

Both are best-effort and use a test sink (notify.set_sink) so no real HTTP is
made; we assert what *would* be delivered given the environment.
"""
from __future__ import annotations

import pytest

from wpguard_mcp import notify


@pytest.fixture()
def captured(monkeypatch):
    deliveries: list = []
    notify.set_sink(lambda ds: deliveries.extend(ds))
    # Clear all relevant env so each test sets exactly what it needs.
    for var in (
        notify.CLOUD_URL_ENV,
        notify.CLOUD_KEY_ENV,
        notify.NOTIFY_WEBHOOKS_ENV,
        notify.NOTIFY_EVENTS_ENV,
    ):
        monkeypatch.delenv(var, raising=False)
    yield deliveries
    notify.set_sink(None)


PACKET = {
    "id": "abc123",
    "site": "example.com",
    "target": "option:blogname",
    "summary": "rename blog",
    "risk": "low",
    "status": "proposed",
    "opened_at": "2026-07-16T00:00:00+00:00",
}


def test_nothing_configured_no_deliveries(captured):
    notify.emit_event("packet_proposed", PACKET)
    assert captured == []


def test_cloud_hook_reports_lifecycle_event(captured, monkeypatch):
    monkeypatch.setenv(notify.CLOUD_URL_ENV, "https://cloud.example/report")
    monkeypatch.setenv(notify.CLOUD_KEY_ENV, "secret-key")

    notify.emit_event("packet_proposed", PACKET)

    assert len(captured) == 1
    d = captured[0]
    assert d.url == "https://cloud.example/report"
    assert d.headers["Authorization"] == "Bearer secret-key"
    assert d.payload["packet_id"] == "abc123"
    assert d.payload["site"] == "example.com"
    assert d.payload["type"] == "packet.proposed"
    assert len(d.payload["digest"]) == 64
    # Metadata only -- never full content / credentials.
    assert "previous_value" not in d.payload
    assert "untrusted_content" not in d.payload


def test_cloud_key_optional(captured, monkeypatch):
    monkeypatch.setenv(notify.CLOUD_URL_ENV, "https://cloud.example/report")
    notify.emit_event("packet_closed", PACKET)
    assert "Authorization" not in captured[0].headers


def test_webhook_notifies_on_default_events(captured, monkeypatch):
    monkeypatch.setenv(notify.NOTIFY_WEBHOOKS_ENV, "https://hooks.slack/x, https://discord/y")

    notify.emit_event("packet_proposed", PACKET)

    assert len(captured) == 2
    # Slack + Discord compatible body.
    assert "text" in captured[0].payload
    assert "content" in captured[0].payload
    assert "abc123" in captured[0].payload["text"]


def test_webhook_respects_event_filter(captured, monkeypatch):
    monkeypatch.setenv(notify.NOTIFY_WEBHOOKS_ENV, "https://hooks.slack/x")
    monkeypatch.setenv(notify.NOTIFY_EVENTS_ENV, "packet_closed")

    notify.emit_event("packet_proposed", PACKET)  # not in filter
    assert captured == []

    notify.emit_event("packet_closed", PACKET)  # in filter
    assert len(captured) == 1


def test_tier3_always_notifies_even_if_excluded(captured, monkeypatch):
    monkeypatch.setenv(notify.NOTIFY_WEBHOOKS_ENV, "https://hooks.slack/x")
    monkeypatch.setenv(notify.NOTIFY_EVENTS_ENV, "packet_closed")  # deliberately excludes tier3

    notify.emit_event("tier3_eval_fired", {**PACKET, "status": "approved"})

    assert len(captured) == 1
    assert "Tier 3" in captured[0].payload["text"]


def test_emit_is_best_effort_and_never_raises(monkeypatch):
    # Real dispatch path (no sink): an unreachable endpoint must not propagate.
    notify.set_sink(None)
    monkeypatch.setenv(notify.CLOUD_URL_ENV, "http://127.0.0.1:1/definitely-not-listening")

    joined = {"count": 0}
    real_thread = notify.threading.Thread

    class ImmediateThread(real_thread):
        def start(self):  # run synchronously so we actually exercise _http_post
            joined["count"] += 1
            self.run()

    monkeypatch.setattr(notify.threading, "Thread", ImmediateThread)

    # Must return cleanly even though the POST fails.
    assert notify.emit_event("packet_proposed", PACKET) is None
    assert joined["count"] == 1
