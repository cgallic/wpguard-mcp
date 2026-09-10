"""Rendered, read-only page verification with durable browser evidence."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .. import config
from ..config import get_site_registry
from . import pages

DEFAULT_VIEWPORTS = {"desktop": {"width": 1440, "height": 1000}, "mobile": {"width": 390, "height": 844}}
MAX_EXPECTED_TEXT = 25
ALLOW_PRIVATE_ENV = "WPGUARD_RENDER_ALLOW_PRIVATE"


class BrowserUnavailableError(RuntimeError):
    """Raised when Playwright or its Chromium runtime is unavailable."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")[:80] or "page"


def _resolve_page(site: str, page_id: int) -> tuple[dict[str, Any], str]:
    normalized_id = pages._page_id(page_id)
    page = pages._read_page(get_site_registry().get(site), normalized_id)
    url = str(page.get("link", "")).strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"page {normalized_id} has no renderable HTTP(S) link")
    _assert_public_url(url)
    return page, url


def _assert_public_url(url: str) -> None:
    if os.environ.get(ALLOW_PRIVATE_ENV) == "1":
        return
    parsed = urlparse(url)
    hostname = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("render URL must use HTTP(S) and include a hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError(f"render hostname could not be resolved: {hostname}") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError(
            "render URL resolves to a private or non-global address; set "
            f"{ALLOW_PRIVATE_ENV}=1 only when this registered site is intentionally private"
        )


def _route_public_only(route) -> None:
    try:
        _assert_public_url(route.request.url)
    except ValueError:
        route.abort("blockedbyclient")
        return
    route.continue_()


def _browser_factory():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserUnavailableError(
            "Rendered verification requires Playwright. Install it with `pip install 'wpguard-mcp[browser]'` "
            "and then run `playwright install chromium`."
        ) from exc
    return sync_playwright


def _inspect_viewport(page, *, url: str, name: str, viewport: dict[str, int],
                      expected_text: list[str], screenshot_path: Path) -> dict[str, Any]:
    page.set_viewport_size(viewport)
    if hasattr(page, "route"):
        page.route("**/*", _route_public_only)
    response = page.goto(url, wait_until="networkidle", timeout=30_000)
    _assert_public_url(page.url)
    page.screenshot(path=str(screenshot_path), full_page=True)
    checks = page.evaluate(
        """(expected) => {
          const body = document.body;
          const text = body ? (body.innerText || '') : '';
          const images = Array.from(document.images);
          return {
            title: document.title,
            h1_count: document.querySelectorAll('h1').length,
            h1_text: Array.from(document.querySelectorAll('h1')).map(e => (e.innerText || '').trim()),
            body_text_length: text.length,
            horizontal_overflow_px: body ? Math.max(0, body.scrollWidth - document.documentElement.clientWidth) : 0,
            broken_images: images.filter(i => i.complete && i.naturalWidth === 0).map(i => i.currentSrc || i.src),
            expected_text: expected.map(value => ({value, present: text.includes(value)})),
          };
        }""",
        expected_text,
    )
    status = response.status if response is not None else None
    failures = []
    if status is None or status >= 400:
        failures.append(f"navigation returned HTTP {status}")
    if checks["horizontal_overflow_px"] > 1:
        failures.append(f"horizontal overflow is {checks['horizontal_overflow_px']}px")
    if checks["broken_images"]:
        failures.append(f"{len(checks['broken_images'])} rendered image(s) are broken")
    missing = [item["value"] for item in checks["expected_text"] if not item["present"]]
    if missing:
        failures.append(f"expected text missing: {missing}")
    return {
        "name": name, "viewport": viewport, "final_url": page.url, "http_status": status,
        "screenshot": {"path": str(screenshot_path), "sha256": _sha256_file(screenshot_path)},
        "dom": checks, "status": "fail" if failures else "pass", "failures": failures,
    }


def wp_page_render_verify(site: str, page_id: int, expected_text: list[str] | None = None) -> dict:
    """Render a WordPress page at desktop and mobile sizes and store hashed evidence. Never mutates WordPress."""
    values = expected_text or []
    if not isinstance(values, list) or len(values) > MAX_EXPECTED_TEXT or any(
        not isinstance(value, str) or not value for value in values
    ):
        raise ValueError(f"expected_text must contain at most {MAX_EXPECTED_TEXT} nonempty strings")
    page_record, url = _resolve_page(site, page_id)
    evidence_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"
    evidence_dir = config.STATE_DIR / "render-evidence" / _safe_slug(site) / evidence_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    results = []
    try:
        sync_playwright = _browser_factory()
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:
                raise BrowserUnavailableError(
                    "Playwright is installed but Chromium could not start. Run `playwright install chromium` "
                    "(or `playwright install --with-deps chromium` in Linux containers)."
                ) from exc
            try:
                context = browser.new_context(ignore_https_errors=False)
                browser_page = context.new_page()
                for name, viewport in DEFAULT_VIEWPORTS.items():
                    screenshot_path = evidence_dir / f"{name}.png"
                    try:
                        result = _inspect_viewport(browser_page, url=url, name=name, viewport=viewport,
                                                   expected_text=values, screenshot_path=screenshot_path)
                    except Exception as exc:
                        result = {
                            "name": name, "viewport": viewport, "final_url": browser_page.url,
                            "http_status": None, "screenshot": None, "dom": None, "status": "fail",
                            "failures": [f"browser verification failed: {type(exc).__name__}: {exc}"],
                        }
                    results.append(result)
                context.close()
            finally:
                browser.close()
    except Exception:
        if not any(evidence_dir.iterdir()):
            evidence_dir.rmdir()
        raise
    failures = [failure for result in results for failure in result["failures"]]
    receipt = {
        "schema_version": 1, "evidence_id": evidence_id,
        "captured_at": datetime.now(timezone.utc).isoformat(), "site": site,
        "page": {"id": page_record["id"], "title": page_record.get("title", ""),
                 "slug": page_record.get("slug", ""), "resolved_url": url},
        "read_only": True, "status": "fail" if failures else "pass", "failures": failures,
        "viewports": results,
    }
    receipt_path = evidence_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {**receipt, "receipt": {"path": str(receipt_path), "sha256": _sha256_file(receipt_path)}}
