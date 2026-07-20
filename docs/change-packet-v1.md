# Change Packet — v1 Schema Reference (as implemented)

This document describes the Change Packet object exactly as `wpguard-mcp`
implements it today. "v1" in the title names this document's snapshot of the
current, shipped behavior — it is not a version number the code itself
tracks anywhere (see gap table row "Schema version": there is no
`schema_version` field on the object at all).

Every claim below is grounded in a specific function, class, or test in this
repository. Where the code doesn't do something, this document says so
explicitly rather than describing an aspiration as if it were current
behavior.

Primary source files:

- `src/wpguard_mcp/guard.py` — `ChangePacket`, `Snapshot`, `PacketStore`,
  `SnapshotStore`, `build_change_digest`, `require_approved_packet`.
- `src/wpguard_mcp/tools/packets.py` — `packet_open`, `packet_approve`,
  `packet_log`, `packet_close`, `packet_list` (the MCP tools that drive the
  lifecycle).
- `src/wpguard_mcp/tools/mutate.py` — the guarded Tier 2/3 tools
  (`wp_mutate_option`, `wp_mutate_post_meta`, `wp_mutate_post_content`,
  `wp_eval`) that compute the digest and call the guard.
- `src/wpguard_mcp/audit.py` — read-only reporting view over the packet +
  snapshot ledgers.
- `src/wpguard_mcp/notify.py` — the separate, best-effort outbound event
  envelope sent to a paired Cloud instance or webhook.

Corroborating tests: `tests/test_guard.py`, `tests/test_locks.py`,
`tests/test_guard_enumeration.py`, `tests/test_tools_flow.py`.

---

## 1. v1 today: the exact JSON shape

### 1.1 Four distinct shapes, not one

Anyone reading this codebase to understand "the packet schema" will run into
**four different JSON shapes** that all describe a change packet at
different points in its life. They are easy to conflate, so this document
keeps them separate:

1. **`ChangePacket.to_dict()`** — the object every packet tool
   (`packet_open`, `packet_approve`, `packet_log`, `packet_close`,
   `packet_list`) returns to the MCP caller. This is the canonical, current
   "packet schema" and is what section 1.2 documents.
2. **The on-disk JSONL event log** (`state/packets/packets.jsonl`) — what is
   actually persisted. It is *not* one row per packet; it's an append-only
   log of `open` / `approve` / `log` / `close` events that gets replayed to
   reconstruct the object in (1). See section 1.3.
3. **`Snapshot.to_dict()`** — a separate, related object (previous/new value
   capture), persisted to its own ledger (`state/packets/snapshots.jsonl`),
   joined to a packet only by `packet_id`. See section 1.4.
4. **The Cloud notify envelope** — a fourth, independently-shaped payload
   that `notify.py` builds only when POSTing an event to an optional,
   paired Cloud endpoint or webhook. It is a lossy, best-effort
   transformation of (1), never read back, and never persisted locally. See
   section 1.5. It's documented here mainly to warn readers not to mistake
   it for the packet's real schema.

### 1.2 `ChangePacket` (`guard.py`, lines ~153–189)

`ChangePacket` is a `@dataclass`. `to_dict()` is `dataclasses.asdict(self)`,
which serializes **only declared fields** — the two `@property` methods
(`is_open`, `is_approved`) are computed convenience accessors and are **not**
present in the returned/serialized dict. A caller that only sees the JSON
(e.g., over MCP) must derive openness from `status` + `closed_at` itself.

| Field | Type | Default | Set by / when |
|---|---|---|---|
| `id` | `str` | — (always set) | `PacketStore.open_packet()`: `uuid.uuid4().hex[:12]`, a 12-char lowercase hex id. Immutable after creation. |
| `site` | `str` | — (required) | Caller argument to `packet_open(site=...)`. Immutable — no rename/move operation exists. |
| `summary` | `str` | — (required) | Caller argument to `packet_open(summary=...)`. Free text. Immutable after open — `packet_log` only appends to `log`, it never edits `summary`. |
| `risk` | `str` | `"low"` | Caller argument to `packet_open(risk=...)`. **Free text, not an enum** — no validation anywhere accepts/rejects a value. Immutable after open. |
| `target` | `str` | `"*"` (`WILDCARD_TARGET`) | Caller argument to `packet_open(target=...)`. Names the resource this packet covers (e.g. `"option:blogname"`) and doubles as the per-target lock key. Immutable after open. |
| `verb` | `str \| None` | `None` | Caller argument to `packet_open(verb=...)`. Optional. Stored for record-keeping and as one input to the digest (§2), but **not independently checked** by the guard — see §2.4. |
| `change_digest` | `str \| None` | `None` | Caller argument to `packet_open(change_digest=...)`, normally the `change_digest` a mutate tool's dry-run just returned. Optional — this is the crux of §2.4: when `None` (the default), the guard enforces no payload/pre-state binding at all. |
| `status` | `str` | `"proposed"` | Set to `"proposed"` at open. Set to `"approved"` only via `packet_approve` → `PacketStore.approve_packet`. Set to `"closed"` only via `packet_close` → `PacketStore.close_packet`. One-way: `proposed → approved → closed`, or `proposed → closed` directly (a packet can be abandoned without ever being approved). No `"rejected"`/`"denied"` status exists — see gap table. |
| `approver` | `str \| None` | `None` | Caller argument to `packet_approve(approver=...)`. Free text (username, agent id, `"policy:auto"`, or `"cloud:<remote approver>"` from `cloud.poll_decisions`) — **not authenticated against any identity system**. |
| `opened_at` | `str` (ISO 8601, UTC) | — (always set) | `PacketStore.open_packet()`, server-generated via `_now()` = `datetime.now(timezone.utc).isoformat()`. Immutable. |
| `approved_at` | `str \| None` (ISO 8601, UTC) | `None` | `PacketStore.approve_packet()`, server-generated `_now()`. Not caller-suppliable through the public API. |
| `closed_at` | `str \| None` (ISO 8601, UTC) | `None` | `PacketStore.close_packet()`, server-generated `_now()`. Doubles as the "is this packet open" signal (`is_open` property = `closed_at is None`), but again: that property is not itself serialized. |
| `outcome` | `str \| None` | `None` | Caller argument to `packet_close(outcome=...)`. Free text. May be **overwritten** by `packets.py:packet_close()` before the store call, to the string `f"verify_failed: {drift_summary} (see durable_check)"`, if an opt-in durable re-check (see below) finds drift. |
| `log` | `list[dict]` | `[]` | Each entry is `{"at": <ISO 8601 str>, "message": <str>}`. Appended by `packet_log(packet_id, message)`. Also auto-appended exactly once by each mutate tool immediately after a successful `apply=True` write, e.g. `"applied wp_mutate_option(blogname) -- snapshot 9f8e7d6c5b4a"`. |

Example of the dict every packet tool returns (values illustrative):

```json
{
  "id": "a1b2c3d4e5f6",
  "site": "example-blog",
  "summary": "Update tagline for spring promo",
  "risk": "low",
  "target": "option:blogdescription",
  "verb": "wp_mutate_option",
  "change_digest": "<sha256 hex, 64 chars>",
  "status": "approved",
  "approver": "connor",
  "opened_at": "2026-07-20T18:03:11.123456+00:00",
  "approved_at": "2026-07-20T18:04:02.001122+00:00",
  "closed_at": null,
  "outcome": null,
  "log": []
}
```

**Bypass edge case:** when `WPGUARD_BYPASS_GUARD=1` and no approved packet
exists, `require_approved_packet` fabricates and returns a synthetic,
in-memory `ChangePacket(id="bypass", site=site, summary="GUARD BYPASSED via
WPGUARD_BYPASS_GUARD", risk="unknown", status="approved")`. This object is
**never written** to `packets.jsonl` — if a caller inspects the returned
dict it will look like a real packet (`id: "bypass"`) but has no ledger
entry and will not appear in `packet_list()` or `wpguard audit`.

**`packet_close`'s return value carries one extra, non-persisted key.** When
`durable_check_delay_seconds` is passed, `packets.py:packet_close()` adds
`result["durable_check"] = {...}` to the dict it returns from the tool call,
but this key is **not** a `ChangePacket` field and is not written to
`packets.jsonl`. It exists only in that one tool response (and whatever
`notify.py` derives from it for an outbound event — see §1.5). Replaying the
ledger later does not recover it.

### 1.3 On-disk representation: an append-only event log, not a packet table

`PacketStore` (`guard.py`) persists to `state/packets/packets.jsonl`
(path overridable via `WPGUARD_STATE_DIR`). It is **event-sourced**: every
lifecycle call appends exactly one JSON line, and `ChangePacket` objects are
rebuilt in memory by replaying all lines in file order (`PacketStore._load`
→ `_apply`). There is no update-in-place and no delete; `_append()` always
opens the file in `"a"` mode.

The four event shapes actually written to disk:

```jsonc
// packet_open()
{"event": "open", "id": "...", "site": "...", "summary": "...", "risk": "...",
 "target": "...", "verb": "...", "change_digest": "...", "opened_at": "..."}

// packet_approve()
{"event": "approve", "id": "...", "approver": "...", "approved_at": "..."}

// packet_log()
{"event": "log", "id": "...", "message": "...", "at": "..."}

// packet_close()
{"event": "close", "id": "...", "outcome": "...", "closed_at": "..."}
```

Implication for any future schema work: the durable source of truth is this
event stream, not a single packet row. A `schema_version` or hash-chain
field (see gap table) would need to be added to each event shape, not just
to the derived `ChangePacket` dataclass — and old lines in an existing
`packets.jsonl` would replay through `_apply()` without it, so any such
change needs an explicit default/migration story.

### 1.4 `Snapshot` (`guard.py`, lines ~445–463) — the companion object

One `Snapshot` is recorded per `apply=True` write that succeeds in reading a
"previous value" (i.e., every guarded tool except the no-op case). A single
approved packet with a wildcard (`"*"`) or otherwise broad `target` can
accumulate more than one snapshot, since `require_approved_packet` only
checks target *overlap*, not a strict 1:1 target match.

| Field | Type | Default | Set by / when |
|---|---|---|---|
| `id` | `str` | — | `SnapshotStore.record()`: `uuid.uuid4().hex[:12]`. |
| `packet_id` | `str` | — | Passed by the calling mutate tool; always the approved packet's `id`. This is the *only* link between a snapshot and its packet (one-directional — see gap table "snapshot references"). |
| `site` | `str` | — | Passed by the calling mutate tool. |
| `tool` | `str` | — | Passed by the calling mutate tool, e.g. `"wp_mutate_option"`. |
| `target` | `str` | — | Same target string used in the digest/lock for this write. |
| `previous_value` | `Any` | — | The live value read immediately before the write (or `None` for `wp_eval`, which has no well-defined "previous state"). |
| `new_value` | `Any` | `None` | The value that was written (or the value the tool expects post-write). `None` for `wp_eval`. |
| `reread` | `list \| None` | `None` | A `[kind, *args]` spec (e.g. `["option", "blogname"]`, `["post_meta", 12, "_thumbnail_id"]`, `["post_content", 12]`) telling `packet_close`'s optional durable check how to re-read this value later. `None` means "no clean re-read available" (always true for `wp_eval`, and for the companion-plugin `wp_mutate_post_content` path when the previous content wasn't a string). |
| `taken_at` | `str` (ISO 8601, UTC) | — | `_now()` at record time. |

Persisted as one JSON object per line, appended (never replayed/reduced —
unlike packets, there's no event-sourcing here, each line already *is* the
final object). Retrieved via `SnapshotStore.list_for_packet(packet_id)`,
which does a full linear scan of `snapshots.jsonl` filtering on
`packet_id`.

`audit.py:build_report()` is the only place packets and snapshots are
joined for reporting: it attaches `record["snapshots"] = [...]` onto each
packet dict at read time. This join is not persisted; it's recomputed on
every `wpguard audit` invocation.

### 1.5 The Cloud notify envelope is a different, fourth shape

`notify.py:_cloud_payload(event, packet)` builds the JSON body POSTed to
`WPGUARD_CLOUD_REPORT_URL` (or a paired Cloud instance's `/api/v1/events`)
when `packet_open` / `packet_approve` / `packet_close` / a Tier 3 `wp_eval`
fires `emit_event(...)`. This transformation only runs for events in
`LIFECYCLE_EVENTS` (`packet_proposed`, `packet_approved`, `packet_closed`,
`packet_verify_failed`, `tier3_eval_fired`), is fire-and-forget on a daemon
thread, and is **never read back** — it is not part of the local schema, but
worth documenting because it's the one place several aspirational-sounding
field names (`digest`, `environment`, `requestedBy`, `preview`) already
exist as literal JSON keys, which can be misleading:

- `environment` is **hardcoded to the literal string `"production"`** on
  every event, unconditionally — there is no actual environment concept
  anywhere else in the codebase (see gap table).
- `requestedBy` reads `packet.get("requested_by")`, but no code path ever
  sets a `requested_by` key on a packet dict — `ChangePacket` has no such
  field — so this is **always** the fallback literal `"local-agent"` in
  current code.
- `preview` is **hardcoded to `None`** on every event. Nothing is ever sent.
- `digest` prefers `packet.get("change_digest")`, but if that's `None`
  (which it is whenever the packet wasn't opened with one — see §2.4) it
  falls back to a **second, different digest algorithm**: SHA-256 of
  `json.dumps({"packet_id", "site", "target", "summary", "risk",
  "opened_at"}, sort_keys=True, separators=(",", ":"))`. This is not
  `build_change_digest` and does not include `verb`, `current_etag`, or the
  mutation `payload` — it exists only so the outbound event always has
  *some* digest-shaped value, not as a security binding.
- `transport` is hardcoded to the literal string `"local"`.
- Cloud/instance identity is carried **implicitly** via the outbound
  request's `Authorization: Bearer <cloud token>` header
  (`cloud.CloudConfig.token`), not as an explicit field in this payload —
  there is no `instanceId` key in the body.

---

## 2. Digest computation

### 2.1 The function

`build_change_digest()` in `guard.py`:

```python
def build_change_digest(site, verb, target, current_etag, payload) -> str:
    canonical = {
        "site": site,
        "verb": verb,
        "target": target,
        "current_etag": current_etag,
        "payload": payload,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
```

Algorithm: SHA-256 over a JSON-canonicalized encoding (`sort_keys=True`
for deterministic key order, minimal `separators=(",", ":")` so
whitespace differences can't change the hash, `ensure_ascii=False` so
non-ASCII text is hashed as literal UTF-8 rather than escaped). Output is a
64-character lowercase hex string.

`mutate.py` wraps it as `_change_digest(site, verb, target, current_etag,
payload)`, a thin pass-through with the same five inputs. Every Tier 2/3
tool calls this **unconditionally**, on both dry-run and apply calls, before
branching on `apply`.

### 2.2 Inputs, precisely

| Input | Where it comes from |
|---|---|
| `site` | The tool call's `site` argument, verbatim. |
| `verb` | A Python string literal at the call site inside each tool (e.g. `mutate.py` passes the literal `"wp_mutate_option"` from inside `wp_mutate_option()` itself) — not derived from any request metadata, but also not independently caller-suppliable, since it's hardcoded per tool function. |
| `target` | Built per-tool: `f"option:{option_name}"`, `f"post:{post_id}:{meta_key}"`, `f"post:{post_id}:content"`, or the literal `"raw_php_eval"` for `wp_eval`. |
| `current_etag` | `_etag(value) = hashlib.sha256(str(value).encode()).hexdigest()[:16]` — a 16-hex-char fingerprint of the **live** previous value, read immediately before the digest is computed. For `wp_eval`, this is passed as `None` (there is no well-defined "current value" for arbitrary PHP), so every `wp_eval` digest for the same `site` + `php_code` is identical regardless of when it's computed — no pre-state binding for Tier 3. |
| `payload` | A tool-specific dict of the exact normalized mutation arguments only — e.g. `{"option_name": ..., "new_value": ...}` for `wp_mutate_option`, `{"post_id": ..., "meta_key": ..., "new_value": ...}` for `wp_mutate_post_meta`, `{"post_id": ..., "search": ..., "replace": ...}` for `wp_mutate_post_content`, `{"php_code": ...}` for `wp_eval`. This dict itself is **never persisted** — only its contribution to the final hash survives. |

### 2.3 When it's computed

Inside every Tier 2/3 tool, on **every call**, dry-run or apply, before the
`if not apply:` branch returns the preview. This means:

- A dry-run's response includes `change_digest` computed from the value
  read *at dry-run time*.
- An apply call recomputes `change_digest` from-scratch using whatever
  `previous_value` it reads *at apply time* — i.e., from current live
  state, not from a cached dry-run result. If the live value drifted
  between preview and apply, `current_etag` (and therefore `change_digest`)
  differs automatically, with no separate drift-detection step required.

### 2.4 What "binding" actually enforces today (the important nuance)

`require_approved_packet(store, site, target=None, change_digest=None)` in
`guard.py` is the single shared gate. Its logic, exactly:

1. Look up the most recently opened, still-open, **approved** packet for
   `site` (`store.get_approved_open_packet(site)`). If none exists, raise
   (distinguishing "proposed but not approved yet" from "nothing at all" in
   the error message), or fall back to the bypass packet if
   `WPGUARD_BYPASS_GUARD=1`.
2. If a `target` was passed (every mutate tool always passes one) **and**
   it does not overlap the packet's stored `target`
   (`_targets_overlap`, which treats `"*"` as matching anything on either
   side) → raise `PacketRequiredError`.
3. **Only if `packet.change_digest is not None`**: compare it to the
   freshly recomputed `change_digest` from step-2's caller. If they differ,
   raise `PacketRequiredError` ("...is bound to a different change digest.
   The payload or pre-change state differs from the reviewed dry run;
   re-preview and re-approve."). **If `packet.change_digest is None` — the
   default, i.e. the packet was opened without passing `change_digest=` —
   this check is skipped entirely.**

The consequence: exact-payload binding is **opt-in per packet**, not a
structural guarantee of the guard function itself. A packet opened with
just `site` and the default `target="*"` and no `change_digest` (all of
which the tool signature permits) will, once approved, authorize **any**
Tier 2/3 write to **any** target on that site — the guard only checks site
match and (trivially-satisfied, since `target="*"`) target overlap. This is
consistent with the README's own note that "legacy packets without a digest
remain supported during the alpha transition."

`verb` is folded into the digest's canonical dict (§2.1), so if a packet
*is* digest-bound, switching to a different tool/verb while reusing the
digest changes the hash and is rejected. But `require_approved_packet`
takes no `verb` parameter and never compares `packet.verb` to anything
directly — verb-level protection exists only as a side effect of digest
binding, and only when digest binding is in effect.

This behavior is directly exercised by
`tests/test_tools_flow.py::test_exact_change_packet_allows_only_previewed_payload`:
opening a packet with `change_digest=preview["change_digest"]` and then
attempting `apply=True` with a *different* `new_value` raises
`PacketRequiredError` matching `"bound to a different change digest"`;
retrying with the original, previewed value succeeds.

### 2.5 A separate, independent, also-opt-in check: `expected_etag`

Distinct from digest binding, each mutate tool also accepts an
`expected_etag` argument. If the caller passes it (from a prior dry-run's
`etag`), `_check_etag()` compares it to the etag of the value just read live
and raises `ConflictError` (not `PacketRequiredError`) on mismatch — this
is optimistic concurrency against a *stale read*, independent of whether the
packet itself is digest-bound. Like digest binding, it is opt-in: omitting
`expected_etag` skips this check entirely.

---

## 3. Gap table: aspirational field vs. implemented today

Legend: **Yes** = implemented and enforced as described. **Partial** =
field/mechanism exists but differs materially from the aspiration (missing
enforcement, missing sub-part, or opt-in rather than mandatory). **No** =
not implemented; nothing in the code does this today.

### Identity and routing

| Aspirational field | Implemented? | Detail / where it would need to be added |
|---|---|---|
| Packet ID | Yes | `ChangePacket.id`, §1.2. |
| Schema version | No | No `schema_version`/`version` field anywhere on `ChangePacket`, `Snapshot`, or the four JSONL event shapes. Would need to be added to the dataclass, the `open` event shape, and `_apply()`'s replay logic, plus a default for existing `packets.jsonl` lines that predate it. |
| Organization ID | No | No org/tenant concept exists anywhere in `guard.py`, `packets.py`, or `config.py`. |
| Instance ID | Partial | `cloud.CloudConfig.instance_id` exists, but at the *paired-install* level (`state/config/cloud.json`), not per-packet. It's carried implicitly by the bearer token on outbound Cloud requests (§1.5), never as an explicit field on a `ChangePacket` or in the notify payload body. Would need to be threaded into the `ChangePacket` dataclass and the `open` event. |
| Site ID | Yes (as a name, not a UUID) | `ChangePacket.site` is the free-text site name used as the `SiteRegistry` key (`config.py:SiteConfig.name`), not a stable synthetic ID. |
| Environment ID | No | `notify.py` hardcodes `"environment": "production"` unconditionally on every outbound event. `SiteConfig` (`config.py`) has no `environment` field, and nothing distinguishes staging from production sites today. |
| Requester identity | No | No `requester`/`requested_by` field on `ChangePacket`. `notify.py` defensively reads `packet.get("requested_by")` but nothing ever sets that key, so it's always the fallback literal `"local-agent"`. Would need a new field on `ChangePacket` + `packet_open(...)`, ideally sourced from the authenticated caller (see next row) rather than trusted as free-text caller input. |
| Agent/client identity | No | `auth.py`/`policy.py` authenticate a bearer **token** to a **scope** (`recon`/`mutate`/`admin` — `policy.SCOPE_LEVELS`), not to an individual agent or client identity. No per-caller identity is threaded from the auth layer into a packet. |

### Arguments and target

| Aspirational field | Implemented? | Detail / where it would need to be added |
|---|---|---|
| Tool/verb name | Partial | `ChangePacket.verb` exists and is stored, but it's optional (default `None`) and `require_approved_packet` never compares it directly — it only matters indirectly, and only when the packet is also digest-bound (§2.4). |
| Exact normalized arguments (raw, persisted) | No | The `payload` dict that feeds the digest (§2.2) is constructed transiently inside each mutate tool call and is **never persisted** to `packets.jsonl` or the `ChangePacket` object — only its hash survives, and only if the caller opted in. |
| Canonical hash of arguments | Partial | This is `change_digest` (§2). The mechanism exists and is cryptographically real (SHA-256 over a canonical JSON encoding), but recording it on the packet is **opt-in** (`packet_open(change_digest=...)` defaults to `None`), so "implemented" is true only for packets that choose to set it — see §2.4. |
| Target resources | Yes (single string, not a list) | `ChangePacket.target`, defaults to `"*"` (whole-site wildcard). No support for a packet naming multiple discrete resources. |

### Risk and summary

| Aspirational field | Implemented? | Detail / where it would need to be added |
|---|---|---|
| Risk classification | Partial | `ChangePacket.risk` is free text (default `"low"`) with **no enum, no validation, and no automatic classifier** — `policy.py`'s tiers (`TOOL_TIERS`) gate tool access by token scope, not by per-packet risk. Any string is accepted. |
| Risk reason | No | No dedicated field distinct from `summary`. |
| Human summary | Yes | `ChangePacket.summary`, required at `packet_open`. |

### Pre-change state and preview

| Aspirational field | Implemented? | Detail / where it would need to be added |
|---|---|---|
| Pre-change state hash/ETag | Partial | `_etag()` (SHA-256[:16] of `str(value)`) exists and is used two ways: (a) folded into `change_digest` as `current_etag`, and (b) surfaced standalone as `etag` in every dry-run response for `expected_etag`/optimistic-concurrency checks (§2.5). It is **not** a persisted field on `ChangePacket` itself — only its contribution to `change_digest` is stored, and only when digest-bound. |
| Sanitized preview/diff | No | Dry-run responses do return human-readable preview data (`previous_value`/`proposed_value`, `match_count`, etc.) but this is a transient tool-call return value, never written to `ChangePacket` or `packets.jsonl`. `notify.py` explicitly hardcodes `"preview": None` on every outbound event — confirmed nothing is ever transmitted either. |
| Requested expiration time | No | No `expires_at`/TTL field on `ChangePacket`. The only TTL in the codebase is the **per-target lock** TTL (`WPGUARD_LOCK_TTL_SECONDS`, default 3600s, `ChangePacket.lock_expires_at()`/`lock_is_live()`), which governs whether a *new* `packet_open` can proceed on an overlapping target — it does **not** expire an existing approval. `require_approved_packet` calls `get_approved_open_packet()`, which filters on `is_approved` only; it never checks lock liveness. **An approved-but-never-closed packet remains a valid guard-satisfier indefinitely**, regardless of how old its lock has become. |

### Policy and approval

| Aspirational field | Implemented? | Detail / where it would need to be added |
|---|---|---|
| Policy decision | No | `policy.py:evaluate_request()` produces a `Decision` (allow/401/403/429) per HTTP request based on token scope vs. tool tier and rate limits, but this decision is **never attached to or recorded on a `ChangePacket`** — it's a request-time gate that runs before the tool body executes, with no durable link to the packet the tool call might reference. |
| Matched policy rule | No | `policy.py` has no rule engine — it's a static tool-tier lookup table (`TOOL_TIERS`) plus a fixed-window rate limiter, not configurable policy-as-code, so there is no "matched rule" concept to record. |
| Approver identity | Yes (free text, unauthenticated) | `ChangePacket.approver`, set by `packet_approve(approver=...)`. Not verified against any identity provider — it's trusted caller input. |
| Approver decision (explicit reject) | No | Only an `approve` event/status exists. There is no `"rejected"`/`"denied"` status and no explicit reject event on the packet itself. `cloud.poll_decisions()` handles a remote "rejected" decision by writing a free-text `packet_log` entry, not a structured decision field or status transition. |
| Approver comment | No | No dedicated field. `cloud.poll_decisions()` does receive a `comment` from a remote Cloud decision, but only folds it into the free-text `log` message — never a structured field on the packet. |
| Approver timestamp | Yes | `ChangePacket.approved_at`, server-generated. |
| Approval signature bound to packet digest | No | `packet_approve(packet_id, approver)` is a plain status flip with a free-text `approver` string — no keypair, no HMAC/asymmetric signature, no cryptographic binding artifact. The digest-binding *behavior* described in §2.4 (an approval becomes unusable for a different payload) exists, but there is no signature object; it's an equality check against a stored hash, not a signed attestation. |

### Execution, verification, and closure

| Aspirational field | Implemented? | Detail / where it would need to be added |
|---|---|---|
| Execution result (structured) | Partial | Each mutate tool returns a rich result dict to the MCP caller (`applied`, `packet_id`, `snapshot_id`, `new_value`, ...) and a free-text `packet_log` entry is auto-appended, but neither is a structured, queryable field **on the packet itself** — the tool's return value is never persisted anywhere, and the log entry is a human-readable string, not structured data. |
| Execution timestamps | Partial | The auto-appended `packet_log` entry carries an `at` timestamp, and `Snapshot.taken_at` records when the pre-write snapshot was captured — but there is no dedicated `executed_at` field on `ChangePacket`. |
| Snapshot references | Partial | Every apply creates a `Snapshot` row carrying `packet_id` (§1.4), and `audit.py` joins them at read time — but the reference is one-directional (`Snapshot → packet_id`) and recomputed via full-table scan; `ChangePacket` itself carries no `snapshot_ids` list. |
| Verification result | Partial | The opt-in durable re-check (`packet_close(durable_check_delay_seconds=...)`) produces a `{"durable": bool, "delay_seconds": int, "checks": [...]}` result, but it is returned only in that one tool call's response and is **not persisted** to `ChangePacket`/`packets.jsonl` — replaying the ledger later does not recover it. Manual verification (e.g. an agent doing a Tier 1 read) is only ever recorded as free text via `packet_log`. |
| Verification evidence | Partial | Same mechanism as above — the `checks` list (target, expected vs. actual value) is real evidence, but it's ephemeral to the `packet_close` call unless a human copies it into a log message or captures the tool response externally. |
| Close outcome | Yes | `ChangePacket.outcome`, set at close, or auto-overwritten to `"verify_failed: ..."` when the durable check finds drift. |

### Integrity of the record itself

| Aspirational field | Implemented? | Detail / where it would need to be added |
|---|---|---|
| Append-only storage | Yes | `PacketStore._append()` and `SnapshotStore.record()` only ever open their files in `"a"` mode; there is no update-in-place or delete path anywhere in `guard.py`. |
| Append-only event **hash chain** (tamper-evidence) | No | Being append-only by code convention is not the same as being tamper-evident: there is no `prev_hash`/`event_hash` field linking each JSONL line to a hash of the previous line (or of the previous packet state), and nothing detects an out-of-band edit, truncation, or reordering of `packets.jsonl` or `snapshots.jsonl`. |

### The plan's closing requirement, evaluated directly

> "An approval must authorize the packet digest, not merely a packet ID.
> Any material change to site, target, verb, arguments, preview, or
> expected pre-state invalidates the approval."

**Partial, and conditional.** `site` is always structurally enforced (the
guard looks up packets by site; there's no way to reuse one site's approval
for another). `target` is enforced whenever the packet's `target` is more
specific than the `"*"` default. `verb`, `arguments`, and expected pre-state
(`current_etag`) are enforced **only when the packet was opened with
`change_digest` set** (§2.4) — which is optional, not required by any code
path. `preview` is not part of the digest or the packet at all (it isn't
computed as a persisted preview object — see "Sanitized preview/diff"
above), so there is nothing to invalidate on that axis. A packet opened
without a digest — which the tool signatures fully permit — authorizes any
payload/verb/pre-state on its site+target once approved, contradicting the
"must authorize the digest" requirement as a structural guarantee.
