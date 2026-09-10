"""Execute the actual PHP handler with minimal WordPress stubs, never a live site."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PHP = os.environ.get("WPGUARD_PHP_BINARY") or shutil.which("php")
pytestmark = pytest.mark.skipif(PHP is None, reason="PHP CLI is required for companion route contract tests")
PLUGIN = Path(__file__).resolve().parents[1] / "wp-plugin" / "wpguard-companion.php"
HARNESS = r"""<?php
define('ABSPATH', __DIR__ . '/');
function add_action($hook, $callback) {}
class WP_REST_Request {
    private $params;
    function __construct($params) { $this->params = $params; }
    function get_param($name) { return $this->params[$name] ?? null; }
}
class WP_REST_Response {
    public $data;
    public $status;
    function __construct($data, $status) { $this->data = $data; $this->status = $status; }
}
function get_post($id) { return (object) array(
    'ID' => $id, 'post_content' => $GLOBALS['content'], 'post_name' => 'example',
    'post_status' => 'publish', 'post_type' => 'page', 'post_modified_gmt' => '2026-01-01 00:00:00'
); }
function get_the_title($post) { return 'Example'; }
function get_permalink($post) { return 'https://example.test/example/'; }
function wp_update_post($data) {
    $GLOBALS['writes'][] = $data;
    $GLOBALS['content'] = $data['post_content'];
    return $data['ID'];
}
function is_wp_error($value) { return false; }
// Minimal sanitizer stub exercises the handler's exact-name comparison.
function sanitize_text_field($value) {
    return trim(preg_replace('/[\r\n\t ]+/', ' ', strip_tags($value)));
}
function get_option($key, $default = null) {
    $GLOBALS['operations'][] = array('get_option', $key);
    return 'previous';
}
function update_option($key, $value) {
    $GLOBALS['operations'][] = array('update_option', $key, $value);
    return true;
}
function get_post_meta($id, $key, $single) {
    $GLOBALS['operations'][] = array('get_post_meta', $id, $key);
    return 'previous';
}
function update_post_meta($id, $key, $value) {
    $GLOBALS['operations'][] = array('update_post_meta', $id, $key, $value);
    return true;
}
$input = json_decode($argv[2], true);
$GLOBALS['content'] = $input['content'];
$GLOBALS['writes'] = array();
$GLOBALS['operations'] = array();
require $argv[1];
$response = wpguard_companion_handle_exec(new WP_REST_Request(array(
    'command' => $input['command'], 'args' => $input['args']
)));
echo json_encode(array('status' => $response->status, 'data' => $response->data,
    'writes' => $GLOBALS['writes'], 'content' => $GLOBALS['content'], 'operations' => $GLOBALS['operations']));
"""


def call_route(tmp_path, content="old and old", command="search_replace_post_content", **overrides):
    args = {"post_id": 42, "search": "old", "replace": "new", "apply": False, **overrides}
    assert PHP is not None
    payload = json.dumps({"content": content, "args": args, "command": command})
    result = subprocess.run(
        [PHP, "-r", HARNESS.removeprefix("<?php"), str(PLUGIN), payload],
        text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


def test_real_php_preview_returns_source_and_counts_without_writing(tmp_path):
    result = call_route(tmp_path)
    assert result["status"] == 200
    assert result["data"]["previous_content"] == "old and old"
    assert result["data"]["match_count"] == result["data"]["matches"] == 2
    assert result["data"]["supports_expected_content_sha256"] is True
    assert result["data"]["applied"] is False
    assert result["writes"] == []
    assert result["content"] == "old and old"


def test_real_php_rejects_stale_content_before_write(tmp_path):
    stale = hashlib.sha256(b"earlier content").hexdigest()
    result = call_route(tmp_path, apply=True, expected_content_sha256=stale)
    assert result["status"] == 409
    assert result["writes"] == []
    assert result["content"] == "old and old"


def test_real_php_matching_digest_applies_exact_unicode_content(tmp_path):
    content = "old café and old"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    result = call_route(tmp_path, content=content, apply=True, expected_content_sha256=digest)
    assert result["status"] == 200
    assert result["data"]["previous_content"] == content
    assert result["data"]["match_count"] == 2
    assert result["data"]["applied"] is True
    assert result["writes"] == [{"ID": 42, "post_content": "new café and new"}]


@pytest.mark.parametrize("apply", [False, True])
def test_real_php_empty_search_rejected_without_write(tmp_path, apply):
    result = call_route(tmp_path, search="", apply=apply)
    assert result["status"] == 400
    assert result["writes"] == []


def test_real_php_legacy_apply_without_digest_still_supported(tmp_path):
    result = call_route(tmp_path, apply=True)
    assert result["status"] == 200
    assert result["content"] == "new and new"


def test_real_php_invalid_digest_type_rejected_without_write(tmp_path):
    result = call_route(tmp_path, apply=True, expected_content_sha256=[])
    assert result["status"] == 400
    assert result["writes"] == []


def test_real_php_page_replace_content_is_atomic_and_exact(tmp_path):
    content = "current café"
    result = call_route(
        tmp_path,
        content=content,
        command="page_replace_content",
        new_content="restored body",
        expected_content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
    assert result["status"] == 200
    assert result["data"]["updated"] is True
    assert result["data"]["page"]["content"] == "restored body"
    assert result["writes"] == [{"ID": 42, "post_content": "restored body"}]


def test_real_php_page_replace_content_rejects_stale_digest(tmp_path):
    result = call_route(
        tmp_path,
        command="page_replace_content",
        new_content="restored body",
        expected_content_sha256=hashlib.sha256(b"stale").hexdigest(),
    )
    assert result["status"] == 409
    assert result["writes"] == []


@pytest.mark.parametrize(
    "command,field,extra",
    [
        ("update_option", "option_name", {}),
        ("update_post_meta", "meta_key", {"post_id": 42}),
    ],
)
def test_real_php_scalar_updates_reject_stale_rollback_digest(tmp_path, command, field, extra):
    result = call_route(
        tmp_path,
        command=command,
        **{
            field: "protected_key",
            "new_value": "restored",
            "expected_value_sha256": hashlib.sha256(b"not-current").hexdigest(),
            **extra,
        },
    )
    assert result["status"] == 409
    assert not any(operation[0].startswith("update_") for operation in result["operations"])


@pytest.mark.parametrize("command,field", [
    ("get_option", "option_name"), ("update_option", "option_name"),
    ("get_post_meta", "meta_key"), ("update_post_meta", "meta_key"),
])
@pytest.mark.parametrize("name", ["<b>protected_key</b>", " protected_key ", "", None, [], 42])
def test_real_php_rejects_transformed_or_invalid_keys_before_access(tmp_path, command, field, name):
    result = call_route(tmp_path, command=command, **{field: name, "new_value": "new"})
    assert result["status"] == 400
    assert result["operations"] == []
    assert result["writes"] == []


@pytest.mark.parametrize("command,field", [
    ("get_option", "option_name"), ("update_option", "option_name"),
    ("get_post_meta", "meta_key"), ("update_post_meta", "meta_key"),
])
def test_real_php_preserves_exact_literal_keys(tmp_path, command, field):
    name = "plugin:field[0]?*"
    result = call_route(tmp_path, command=command, **{field: name, "new_value": "new"})
    assert result["status"] == 200
    assert result["data"]["option_name" if field == "option_name" else "meta_key"] == name
    operations = result["operations"]
    assert len(operations) == (2 if command.startswith("update") else 1)
    assert all(operation[1 if field == "option_name" else 2] == name for operation in operations)
