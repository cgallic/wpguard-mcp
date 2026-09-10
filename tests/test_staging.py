from unittest.mock import patch

import pytest

from wpguard_mcp.tools.staging import wp_page_stage_and_test


def test_staging_preview_never_writes():
    with patch(
        "wpguard_mcp.tools.staging.pages.wp_page_replace_content", side_effect=[{"site": "stage"}, {"site": "prod"}]
    ) as replace:
        result = wp_page_stage_and_test("prod", "stage", 1, 2, "content")
    assert result["production_unchanged"] is True
    assert all(call.kwargs["apply"] is False for call in replace.call_args_list)


def test_staging_apply_requires_preview_etag():
    with patch("wpguard_mcp.tools.staging.pages.wp_page_replace_content", side_effect=[{}, {}]):
        with pytest.raises(ValueError, match="expected_staging_etag"):
            wp_page_stage_and_test("prod", "stage", 1, 2, "content", apply_to_staging=True)


def test_staging_apply_tests_stage_and_only_previews_production():
    calls = [{"etag": "s"}, {"etag": "p"}, {"applied": True}, {"etag": "fresh"}]
    with (
        patch("wpguard_mcp.tools.staging.pages.wp_page_replace_content", side_effect=calls) as replace,
        patch("wpguard_mcp.tools.staging.render_verify.wp_page_render_verify", return_value={"ok": True}),
    ):
        result = wp_page_stage_and_test(
            "prod", "stage", 1, 2, "content", apply_to_staging=True, expected_staging_etag="s"
        )
    assert result["status"] == "staged_and_tested"
    assert result["production_unchanged"] is True
    assert replace.call_args_list[2].kwargs["site"] == "stage"
    assert replace.call_args_list[2].kwargs["apply"] is True
    assert replace.call_args_list[3].kwargs["site"] == "prod"
    assert replace.call_args_list[3].kwargs["apply"] is False
