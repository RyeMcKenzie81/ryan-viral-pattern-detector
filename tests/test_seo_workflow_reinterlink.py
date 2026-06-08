"""Tests for the D2 re-render -> re-interlink hook (SEOWorkflowService).

Re-renders regenerate content_html from phase_c_output (which has no links), so
after an explicit re-render the interlinks must be rebuilt. The hook routes
through the canonical InterlinkingService.interlink() and is non-fatal.
"""

from unittest.mock import MagicMock, patch

IL_PATH = "viraltracker.services.seo_pipeline.services.interlinking_service.InterlinkingService"


def _svc(mock_db):
    from viraltracker.services.seo_pipeline.services.seo_workflow_service import SEOWorkflowService
    return SEOWorkflowService(supabase_client=mock_db)


def _spoke_returns(mock_db, data):
    (mock_db.table.return_value.select.return_value.eq.return_value
     .limit.return_value.execute.return_value) = MagicMock(data=data)


def test_reinterlink_uses_cluster_scope_when_clustered():
    mock_db = MagicMock()
    _spoke_returns(mock_db, [{"cluster_id": "c1"}])
    with patch(IL_PATH) as MockIL:
        inst = MockIL.return_value
        _svc(mock_db)._reinterlink_after_render("a1", "b", "o", push_to_cms=False)
        inst.interlink.assert_called_once()
        kwargs = inst.interlink.call_args.kwargs
        assert kwargs.get("scope") == "cluster"
        assert kwargs.get("cluster_id") == "c1"
        assert kwargs.get("push_to_cms") is False


def test_reinterlink_uses_article_scope_when_standalone():
    mock_db = MagicMock()
    _spoke_returns(mock_db, [])
    with patch(IL_PATH) as MockIL:
        inst = MockIL.return_value
        _svc(mock_db)._reinterlink_after_render("a1", "b", "o", push_to_cms=True)
        kwargs = inst.interlink.call_args.kwargs
        assert kwargs.get("scope") == "article"
        assert kwargs.get("push_to_cms") is True


def test_reinterlink_is_non_fatal():
    mock_db = MagicMock()
    mock_db.table.side_effect = Exception("db down")
    # Must not raise — a re-optimize must not fail because re-linking hiccuped.
    _svc(mock_db)._reinterlink_after_render("a1", "b", "o", push_to_cms=False)
