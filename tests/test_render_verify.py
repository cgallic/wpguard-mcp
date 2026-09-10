from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from wpguard_mcp.tools import render_verify


class FakePage:
    def __init__(self):
        self.url = ""
        self.viewport = {}

    def set_viewport_size(self, viewport):
        self.viewport = viewport

    def goto(self, url, **_kwargs):
        self.url = url
        return SimpleNamespace(status=200)

    def screenshot(self, path, **_kwargs):
        with open(path, "wb") as stream:
            stream.write(f"png:{self.viewport['width']}".encode())

    def evaluate(self, _script, expected):
        return {
            "title": "Synthetic page", "h1_count": 1, "h1_text": ["Synthetic"],
            "body_text_length": 100, "horizontal_overflow_px": 0, "broken_images": [],
            "expected_text": [{"value": value, "present": value != "Missing"} for value in expected],
        }


class FakeBrowser:
    def __init__(self):
        self.page = FakePage()

    def new_context(self, **_kwargs):
        return SimpleNamespace(new_page=lambda: self.page, close=lambda: None)

    def close(self):
        pass


class FakePlaywright:
    def __init__(self):
        self.chromium = SimpleNamespace(launch=lambda **_kwargs: FakeBrowser())

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


def test_render_verify_stores_hashed_desktop_and_mobile_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(render_verify.config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(
        render_verify, "_resolve_page",
        lambda _site, _page_id: ({"id": 7, "title": "Synthetic", "slug": "synthetic"},
                                  "https://example.test/synthetic/"),
    )
    monkeypatch.setattr(render_verify, "_browser_factory", lambda: lambda: FakePlaywright())
    monkeypatch.setattr(render_verify, "_assert_public_url", lambda _url: None)

    result = render_verify.wp_page_render_verify("example", 7, expected_text=["Present", "Missing"])

    assert result["read_only"] is True
    assert result["status"] == "fail"
    assert len(result["viewports"]) == 2
    assert {item["name"] for item in result["viewports"]} == {"desktop", "mobile"}
    assert all(item["screenshot"]["sha256"] for item in result["viewports"])
    receipt_path = tmp_path / "render-evidence" / "example" / result["evidence_id"] / "receipt.json"
    assert result["receipt"]["sha256"] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    assert "expected text missing" in result["failures"][0]


def test_render_verify_rejects_unrenderable_page_link(monkeypatch):
    monkeypatch.setattr(render_verify, "get_site_registry", lambda: SimpleNamespace(get=lambda _site: object()))
    monkeypatch.setattr(
        render_verify.pages, "_read_page",
        lambda _site, _page_id: {"id": 7, "link": "javascript:alert(1)"},
    )
    with pytest.raises(ValueError, match="no renderable HTTP"):
        render_verify.wp_page_render_verify("example", 7)


def test_browser_dependency_failure_has_install_instructions(monkeypatch):
    def missing():
        raise render_verify.BrowserUnavailableError(
            "Rendered verification requires Playwright. Install it with `pip install 'wpguard-mcp[browser]'` "
            "and then run `playwright install chromium`."
        )

    monkeypatch.setattr(render_verify, "_browser_factory", missing)
    with pytest.raises(render_verify.BrowserUnavailableError, match="playwright install chromium"):
        render_verify._browser_factory()


def test_render_verify_has_recon_policy_tier():
    from wpguard_mcp import policy

    assert policy.TOOL_TIERS["wp_page_render_verify"] == 1


def test_render_verify_blocks_private_network_targets(monkeypatch):
    monkeypatch.delenv(render_verify.ALLOW_PRIVATE_ENV, raising=False)
    monkeypatch.setattr(render_verify.socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (None, None, None, None, ("127.0.0.1", 443)),
    ])
    with pytest.raises(ValueError, match="private or non-global"):
        render_verify._assert_public_url("https://localhost/page/")


def test_render_verify_private_network_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv(render_verify.ALLOW_PRIVATE_ENV, "1")
    render_verify._assert_public_url("https://127.0.0.1/page/")
