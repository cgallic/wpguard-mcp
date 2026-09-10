"""Exact-target correction checks backed by caller attestations and replay examples.

This ledger records evidence references; it does not independently authenticate
human acceptance. Like the packet ledger, it supports a single writer process.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .config import STATE_DIR

DEFAULT_CORRECTION_STORE_PATH = STATE_DIR / "corrections" / "corrections.jsonl"
KINDS = {"contains", "not_contains", "equals", "json_pointer_equals", "html_link"}


class CorrectionBlockedError(RuntimeError):
    """A known correction failed or could not be evaluated."""


def _validate_target(target: str) -> None:
    if not isinstance(target, str) or any(c in target for c in "\n\r"):
        raise ValueError("Correction target must be a string without newlines")
    parts = target.split(":", 2)
    option = target.startswith("option:") and bool(target[len("option:"):].strip())
    post = (len(parts) == 3 and parts[0] in {"post", "post_meta"} and parts[1].isascii()
            and parts[1].isdecimal() and int(parts[1]) > 0 and str(int(parts[1])) == parts[1]
            and (parts[2] == "content" if parts[0] == "post" else bool(parts[2].strip())))
    if not (option or post):
        raise ValueError("Use option:key, post:id:content for the body, or post_meta:id:key for metadata")


def _pointer(value: Any, path: str) -> Any:
    if not isinstance(path, str) or (path and not path.startswith("/")):
        raise ValueError("Invalid JSON pointer")
    if not path:
        return value
    for token in path[1:].split("/"):
        i = 0
        while i < len(token):
            if token[i] == "~":
                if i + 1 == len(token) or token[i + 1] not in "01":
                    raise ValueError("Invalid JSON pointer escape")
                i += 1
            i += 1
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value[token]
        elif isinstance(value, list):
            if not token.isascii() or not token.isdecimal() or str(int(token)) != token:
                raise ValueError("Invalid array index")
            value = value[int(token)]
        else:
            raise ValueError("JSON pointer traverses a scalar")
    return value


def _equal(actual: Any, expected: Any) -> bool:
    # JSON equality must not equate Python's True and 1.
    return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(
        expected, sort_keys=True, allow_nan=False
    )


class _LinkParser(HTMLParser):
    """Extract closed anchors, ignoring non-rendered script/style/template data.

    This proves HTML structure and text, not browser visibility or link health.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str | None, str]] = []
        self.href: str | None = None
        self.parts: list[str] | None = None
        self.ignored: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "template"}:
            self.ignored.append(tag)
        if self.ignored:
            return
        if tag == "a":
            if self.parts is not None:
                raise ValueError("Nested anchors cannot be reliably interpreted")
            hrefs = [value for name, value in attrs if name == "href"]
            if len(hrefs) > 1:
                raise ValueError("Duplicate href attributes cannot be reliably interpreted")
            self.href = hrefs[0] if hrefs else None
            self.parts = []
        elif tag == "br" and self.parts is not None:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag == "a" and self.parts is not None:
            self.links.append((self.href, " ".join("".join(self.parts).split())))
            self.parts = None
            self.href = None

    def handle_data(self, data: str) -> None:
        if not self.ignored and self.parts is not None:
            self.parts.append(data)


def _check(kind: str, expected: Any, path: str, value: Any) -> dict:
    try:
        if kind not in KINDS:
            raise ValueError("Unsupported check kind")
        if kind in {"contains", "not_contains"}:
            if not isinstance(value, str) or not isinstance(expected, str) or not expected:
                raise ValueError("Text checks require string input and a nonempty expected string")
            matches = expected in value
            if kind == "not_contains":
                matches = not matches
        elif kind == "html_link":
            if not isinstance(value, str) or not isinstance(expected, dict) or set(expected) != {"href", "text"}:
                raise ValueError("html_link requires HTML text and expected {href: string, text: string}")
            if any(not isinstance(expected[key], str) or not expected[key].strip() for key in ("href", "text")):
                raise ValueError("html_link href and text must be nonempty strings")
            parser = _LinkParser()
            parser.feed(value)
            parser.close()
            if parser.parts is not None:
                raise ValueError("Unclosed anchor cannot be reliably interpreted")
            matches = (expected["href"], " ".join(expected["text"].split())) in parser.links
        elif kind == "equals":
            if isinstance(value, (dict, list)) or isinstance(expected, (dict, list)) or value is None:
                raise ValueError("equals requires present scalar input; use JSON pointer for structured values")
            matches = _equal(value, expected)
        else:
            if isinstance(value, str):
                value = json.loads(value)
            if not isinstance(value, (dict, list)):
                raise ValueError("JSON pointer requires an object or array")
            matches = _equal(_pointer(value, path), expected)
        return {"status": "pass" if matches else "fail"}
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return {"status": "unknown", "reason": str(exc)}


class CorrectionStore:
    def __init__(self, path: Path | str = DEFAULT_CORRECTION_STORE_PATH):
        self.path = Path(path)

    def _records(self) -> dict[str, dict]:
        records: dict[str, dict] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if event["event"] == "record":
                    records[event["record"]["id"]] = event["record"]
                elif event["event"] == "retire":
                    record = records[event["id"]]
                    if record["site"] != event["site"]:
                        raise ValueError("Correction ledger retirement site mismatch")
                    record.update(active=False, retired_at=event["at"], retirement_reason=event["reason"])
                else:
                    raise ValueError("Unsupported correction ledger event")
        return records

    def _append(self, event: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")

    def record(self, site: str, target: str, human_correction: str, source_ref: str,
               kind: str, expected: Any, rejected_value: Any, accepted_value: Any,
               path: str = "", acceptance_ref: str = "", human_requested_basis: str = "") -> dict:
        _validate_target(target)
        for name, value in {"site": site, "human_correction": human_correction, "source_ref": source_ref}.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if not (isinstance(acceptance_ref, str) and acceptance_ref.strip()) and not (
            isinstance(human_requested_basis, str) and human_requested_basis.strip()
        ):
            raise ValueError("Provide acceptance_ref or human_requested_basis as caller attestation")
        if kind not in KINDS or (kind != "json_pointer_equals" and path):
            raise ValueError("Unsupported check kind or path")
        bad = _check(kind, expected, path, rejected_value)
        good = _check(kind, expected, path, accepted_value)
        if bad["status"] != "fail" or good["status"] != "pass":
            raise ValueError("Check must reproduce fail on rejected_value and pass on accepted_value")
        identity = dict(site=site, target=target, human_correction=human_correction, source_ref=source_ref,
                        acceptance_ref=acceptance_ref, human_requested_basis=human_requested_basis,
                        kind=kind, expected=expected, path=path,
                        rejected_value=rejected_value, accepted_value=accepted_value)
        encoded = json.dumps(identity, sort_keys=True, ensure_ascii=False, allow_nan=False)
        correction_id = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        existing = self._records().get(correction_id)
        if existing is not None:
            return deepcopy(existing)
        record = dict(identity, id=correction_id, active=True, created_at=datetime.now(timezone.utc).isoformat(),
                      evidence_status="caller_attested", replay={"rejected": bad, "accepted": good})
        self._append({"event": "record", "record": record})
        return deepcopy(record)

    def list(self, site: str, target: str | None = None) -> list[dict]:
        if target is not None:
            _validate_target(target)
        return [r for r in self._records().values() if r["site"] == site and
                (target is None or r["target"] == target)]

    def retire(self, site: str, correction_id: str, reason: str) -> dict:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Retirement reason is required")
        record = self._records().get(correction_id)
        if record is None or record["site"] != site:
            raise ValueError("Correction not found for this site")
        if record["active"]:
            self._append({"event": "retire", "id": correction_id, "site": site, "reason": reason,
                          "at": datetime.now(timezone.utc).isoformat()})
        return self._records()[correction_id]

    def evaluate(self, site: str, target: str, proposed_value: Any) -> dict:
        _validate_target(target)
        checks = []
        for record in self.list(site, target):
            if record["active"]:
                checks.append(dict(_check(record["kind"], record["expected"], record["path"], proposed_value),
                                   correction_id=record["id"], source_ref=record["source_ref"],
                                   acceptance_ref=record["acceptance_ref"], kind=record["kind"],
                                   evidence_status=record["evidence_status"]))
        statuses = {c["status"] for c in checks}
        status = "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else (
            "pass" if checks else "not_covered")
        return {"site": site, "target": target, "status": status, "checks": checks}


@lru_cache(maxsize=1)
def get_correction_store() -> CorrectionStore:
    return CorrectionStore()


def evaluate_corrections(site: str, target: str, proposed_value: Any) -> dict:
    return get_correction_store().evaluate(site, target, proposed_value)


def assert_corrections_allow(report: dict) -> None:
    if report.get("status") not in {"pass", "not_covered"}:
        raise CorrectionBlockedError("Correction checks failed or are unknown; inspect the dry-run correction report")
