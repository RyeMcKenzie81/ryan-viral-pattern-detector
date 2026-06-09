"""Tests for SEOWorkflowService.regenerate_article safety.

Focus: a same-keyword dedup collision on the job insert must NOT mutate the
article. The field-wipe was moved into _execute_one_off (inside the running
job) precisely so a collision can never leave the article permanently blank.
"""

from unittest.mock import MagicMock

import pytest

BRAND_ID = "22222222-2222-2222-2222-222222222222"
ORG_ID = "33333333-3333-3333-3333-333333333333"
ARTICLE_ID = "66666666-6666-6666-6666-666666666666"


def _make_service(mock_supabase):
    from viraltracker.services.seo_pipeline.services.seo_workflow_service import SEOWorkflowService
    return SEOWorkflowService(supabase_client=mock_supabase)


def test_regenerate_dedup_collision_does_not_wipe_article():
    """If the job insert hits the unique-index dedup, regenerate_article must
    raise ValueError and leave the article untouched (no .update())."""
    mock_db = MagicMock()

    article_row = MagicMock()
    article_row.data = [{
        "id": ARTICLE_ID,
        "keyword": "best hiking boots",
        "project_id": "p1",
        "author_id": "auth1",
        "tags": ["a", "b"],
    }]

    updates_made = []

    def table_side_effect(name):
        chain = MagicMock()
        if name == "seo_articles":
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain
            chain.execute.return_value = article_row

            # Record any update() so we can assert the article was not wiped.
            def _update(payload):
                updates_made.append(payload)
                upd = MagicMock()
                upd.eq.return_value = upd
                upd.execute.return_value = MagicMock(data=[])
                return upd

            chain.update.side_effect = _update
            return chain

        if name == "seo_workflow_jobs":
            chain.insert.return_value = chain
            # Simulate the partial unique index rejecting a duplicate one_off job
            chain.execute.side_effect = Exception(
                'duplicate key value violates unique constraint '
                '"idx_seo_workflow_jobs_dedup_keyword"'
            )
            return chain

        return chain

    mock_db.table.side_effect = table_side_effect

    svc = _make_service(mock_db)

    with pytest.raises(ValueError, match="already running"):
        svc.regenerate_article(
            article_id=ARTICLE_ID,
            brand_id=BRAND_ID,
            organization_id=ORG_ID,  # real UUID -> _resolve_org_id is a no-op
        )

    # The critical assertion: the article was never mutated, so a collision
    # leaves it fully intact and recoverable.
    assert updates_made == [], f"article was wiped on dedup collision: {updates_made}"


def test_regenerate_refuses_locked_article():
    """A content_locked article's body is human-owned on the CMS; regenerate
    (which wipes phase_c_output/content_html in _execute_one_off) must refuse
    and never insert a job, so a bulk 'regenerate failed' sweep can't clobber a
    manual Shopify edit."""
    mock_db = MagicMock()

    article_row = MagicMock()
    article_row.data = [{
        "id": ARTICLE_ID,
        "keyword": "best hiking boots",
        "project_id": "p1",
        "author_id": "auth1",
        "tags": ["a", "b"],
        "content_locked": True,
    }]

    inserted_jobs = []

    def table_side_effect(name):
        chain = MagicMock()
        if name == "seo_articles":
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain
            chain.execute.return_value = article_row
            return chain
        if name == "seo_workflow_jobs":
            def _insert(payload):
                inserted_jobs.append(payload)
                return chain
            chain.insert.side_effect = _insert
            chain.execute.return_value = MagicMock(data=[{"id": "job1"}])
            return chain
        return chain

    mock_db.table.side_effect = table_side_effect

    svc = _make_service(mock_db)

    with pytest.raises(ValueError, match="content_locked"):
        svc.regenerate_article(
            article_id=ARTICLE_ID,
            brand_id=BRAND_ID,
            organization_id=ORG_ID,
        )

    assert inserted_jobs == [], "a job was queued for a locked article"
