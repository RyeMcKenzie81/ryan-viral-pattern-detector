"""Tests for InterlinkingService.find_top_movers — articles whose GSC position
improved most period-over-period, surfaced as inbound-link opportunities.

A fake Supabase honors the eq/in_/gte/lt/not_.is_ filters so the real
recent-vs-prior date-window position-delta logic is exercised. The inbound-link
helpers are patched to canned values to isolate the movement logic.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from viraltracker.services.seo_pipeline.services.interlinking_service import InterlinkingService

NOW = datetime.now(timezone.utc)


def d(days_ago):
    return (NOW - timedelta(days=days_ago)).date().isoformat()


class FakeQuery:
    def __init__(self, table, store):
        self.table = table
        self.store = store
        self.eqs = {}
        self.ins = {}
        self.ranges = []          # (col, op, val)
        self.null_not = []        # cols that must be NOT null
        self._order = None
        self._desc = False
        self._limit = None
        self._page_range = None
        self._negate = False

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.eqs[col] = val
        return self

    def neq(self, col, val):
        return self

    def in_(self, col, vals):
        self.ins[col] = list(vals)
        return self

    @property
    def not_(self):
        self._negate = True
        return self

    def is_(self, col, val):
        if val == "null" and self._negate:
            self.null_not.append(col)
        self._negate = False
        return self

    def gte(self, col, val):
        self.ranges.append((col, ">=", val))
        return self

    def lt(self, col, val):
        self.ranges.append((col, "<", val))
        return self

    def order(self, col, desc=False):
        self._order = col
        self._desc = desc
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._page_range = (start, end)
        return self

    def execute(self):
        return SimpleNamespace(data=self.store.resolve(self))


class FakeStore:
    def __init__(self, articles, analytics):
        self.data = {"seo_articles": articles, "seo_article_analytics": analytics}

    def table(self, name):
        return FakeQuery(name, self)

    def resolve(self, q):
        rows = self.data.get(q.table, [])
        out = []
        for r in rows:
            if any(r.get(c) != v for c, v in q.eqs.items()):
                continue
            if any(r.get(c) not in vals for c, vals in q.ins.items()):
                continue
            if any(r.get(c) is None for c in q.null_not):
                continue
            ok = True
            for col, op, val in q.ranges:
                rv = r.get(col)
                if rv is None or (op == ">=" and not (str(rv) >= str(val))) or (op == "<" and not (str(rv) < str(val))):
                    ok = False
                    break
            if ok:
                out.append(r)
        if q._order:
            out = sorted(out, key=lambda r: r.get(q._order) or "", reverse=q._desc)
        if q._page_range is not None:
            out = out[q._page_range[0]:q._page_range[1] + 1]
        elif q._limit is not None:
            out = out[:q._limit]
        return out


def _article(aid, project="p1"):
    return {"id": aid, "keyword": aid.lower(), "title": f"Article {aid}",
            "published_url": f"https://x.com/{aid}", "project_id": project, "brand_id": "b1"}


def _an(aid, days_ago, pos, impr):
    return {"article_id": aid, "date": d(days_ago), "average_position": pos,
            "impressions": impr, "source": "gsc", "search_type": "web"}


@pytest.fixture
def svc(monkeypatch):
    articles = [_article(x) for x in ("A", "B", "C", "D", "E", "F")]
    analytics = [
        # A: recent avg pos (10,12)=11 over last week, prior 18 -> improved 7, impr 100
        _an("A", 2, 10, 60), _an("A", 3, 12, 40), _an("A", 9, 18, 50),
        # B: 20 vs 15 -> declined, not a mover
        _an("B", 2, 20, 80), _an("B", 9, 15, 70),
        # C: 9.0 vs 9.3 -> improved 0.3 (< min 0.5), not a mover
        _an("C", 2, 9.0, 90), _an("C", 9, 9.3, 80),
        # D: improved but NO prior window data -> can't measure
        _an("D", 2, 5, 100),
        # E: improved 10 but impressions 10 (< min 50) -> excluded
        _an("E", 2, 30, 10), _an("E", 9, 40, 5),
        # F: 4 vs 6 -> improved 2, impr 200 (a smaller mover than A)
        _an("F", 2, 4, 200), _an("F", 9, 6, 150),
    ]
    s = InterlinkingService(supabase_client=FakeStore(articles, analytics))
    monkeypatch.setattr(s, "_batch_count_inbound_links", lambda ids: {"A": 1, "F": 3})
    monkeypatch.setattr(s, "_suggest_inbound_sources",
                        lambda article, aid, max_n=15: [{"article_id": "S1"}, {"article_id": "S2"}])
    return s


class TestFindTopMovers:
    def test_only_improved_articles_with_both_windows_and_enough_impressions(self, svc):
        res = svc.find_top_movers("b1", "org1", days=7, min_impressions=50, min_improvement=0.5)
        ids = {m["article_id"] for m in res["movers"]}
        assert ids == {"A", "F"}   # B declined, C too small, D no prior, E low impressions

    def test_position_delta_and_improvement_computed(self, svc):
        res = svc.find_top_movers("b1", "org1", days=7, min_impressions=50, min_improvement=0.5)
        a = next(m for m in res["movers"] if m["article_id"] == "A")
        # impression-weighted: (10*60 + 12*40) / (60+40) = 10.8, not the plain mean 11.0
        assert a["recent_position"] == 10.8
        assert a["prior_position"] == 18.0
        assert a["position_delta"] == -7.2     # negative = improved
        assert a["improvement"] == 7.2
        assert a["impressions"] == 100

    def test_sorted_by_improvement_desc(self, svc):
        res = svc.find_top_movers("b1", "org1", days=7, min_impressions=50, min_improvement=0.5)
        assert [m["article_id"] for m in res["movers"]] == ["A", "F"]   # 7.0 before 2.0

    def test_surfaces_inbound_count_and_opportunity_count(self, svc):
        res = svc.find_top_movers("b1", "org1", days=7, min_impressions=50, min_improvement=0.5)
        a = next(m for m in res["movers"] if m["article_id"] == "A")
        assert a["inbound_link_count"] == 1            # from patched _batch_count_inbound_links
        assert a["opportunity_count"] == 2             # len(suggested_sources)
        assert len(a["suggested_sources"]) == 2

    def test_no_articles_returns_empty(self, monkeypatch):
        s = InterlinkingService(supabase_client=FakeStore([], []))
        monkeypatch.setattr(s, "_batch_count_inbound_links", lambda ids: {})
        res = s.find_top_movers("b1", "org1")
        assert res == {"movers": [], "total_scanned": 0, "last_synced_at": None}


def test_paginate_loops_across_pages():
    # _paginate must keep paging via .range() until a short page, so big result
    # sets aren't truncated at the row cap.
    store = FakeStore([{"id": str(i)} for i in range(5)], [])
    out = InterlinkingService._paginate(
        lambda: store.table("seo_articles").select("id"), page_size=2
    )
    assert [r["id"] for r in out] == ["0", "1", "2", "3", "4"]   # all 5 despite page size 2
