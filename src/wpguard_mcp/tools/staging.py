"""Pre-production page test against an explicitly registered staging site."""

from __future__ import annotations

from . import pages, render_verify


def wp_page_stage_and_test(
    production_site: str,
    staging_site: str,
    production_page_id: int,
    staging_page_id: int,
    proposed_content: str,
    protected_copy: list[str] | None = None,
    expected_text: str | None = None,
    apply_to_staging: bool = False,
    expected_staging_etag: str | None = None,
) -> dict:
    """Preview or apply a page change on a registered staging peer, then test it.

    This never writes production. With `apply_to_staging=False`, it returns the
    staging and production previews. With `True`, the staging write still needs
    its own exact approved packet and ETag; WPGuard then renders desktop/mobile
    evidence and returns a fresh production preview for a separate approval.
    """
    if production_site == staging_site:
        raise ValueError("production_site and staging_site must be different registered sites")
    preserved = protected_copy or []
    staging_preview = pages.wp_page_replace_content(
        site=staging_site,
        page_id=staging_page_id,
        new_content=proposed_content,
        protected_copy=preserved,
        apply=False,
    )
    production_preview = pages.wp_page_replace_content(
        site=production_site,
        page_id=production_page_id,
        new_content=proposed_content,
        protected_copy=preserved,
        apply=False,
    )
    if not apply_to_staging:
        return {
            "status": "preview",
            "production_unchanged": True,
            "staging_preview": staging_preview,
            "production_preview": production_preview,
        }
    if not expected_staging_etag:
        raise ValueError("expected_staging_etag from the staging preview is required")
    staged = pages.wp_page_replace_content(
        site=staging_site,
        page_id=staging_page_id,
        new_content=proposed_content,
        protected_copy=preserved,
        apply=True,
        expected_etag=expected_staging_etag,
    )
    evidence = render_verify.wp_page_render_verify(
        site=staging_site,
        page_id=staging_page_id,
        expected_text=[expected_text] if expected_text else None,
    )
    return {
        "status": "staged_and_tested",
        "production_unchanged": True,
        "staging_apply": staged,
        "render_evidence": evidence,
        "production_preview": pages.wp_page_replace_content(
            site=production_site,
            page_id=production_page_id,
            new_content=proposed_content,
            protected_copy=preserved,
            apply=False,
        ),
        "next_step": "Review evidence, then open an exact production packet using production_preview.change_digest.",
    }
