"""Tests for ClusterBuildService - turning a Top Mover into a pillar+spoke cluster.

A small fake Supabase (eq/ilike/limit/insert/update) backs the direct table reads
the build does itself; fake cluster/keyword services stand in for the existing
services it orchestrates (and write back to the same store so idempotency on
re-run is exercised for real). The LLM is a canned-payload fake.
"""
import re
from types import SimpleNamespace

import pytest


def _like_to_regex(pattern: str) -> str:
    """Translate a SQL LIKE/ILIKE pattern to a regex (so the fake matches like PG)."""
    out = []
    for ch in pattern:
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return "^" + "".join(out) + "$"

from viraltracker.services.seo_pipeline.services.cluster_build_service import (
    ClusterBuildService,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeQ:
    def __init__(self, table, store):
        self.t = table
        self.s = store
        self.flt = []
        self._ilike = None
        self._limit = None
        self._mode = "select"
        self._data = None

    def select(self, *a, **k):
        self._mode = "select"
        return self

    def insert(self, data):
        self._mode = "insert"
        self._data = data
        return self

    def update(self, data):
        self._mode = "update"
        self._data = data
        return self

    def delete(self):
        self._mode = "delete"
        return self

    def eq(self, col, val):
        self.flt.append((col, val))
        return self

    def ilike(self, col, val):
        self._ilike = (col, val)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        return SimpleNamespace(data=self.s._run(self))


class FakeStore:
    def __init__(self):
        self.tables = {}
        self._ctr = 0

    def table(self, name):
        return FakeQ(name, self)

    def _run(self, q):
        rows = self.tables.setdefault(q.t, [])
        if q._mode == "insert":
            data = dict(q._data)
            if not data.get("id"):
                self._ctr += 1
                data["id"] = f"{q.t}-{self._ctr}"
            rows.append(data)
            return [data]

        def match(r):
            for c, v in q.flt:
                if r.get(c) != v:
                    return False
            if q._ilike:
                c, v = q._ilike
                if not re.match(_like_to_regex(str(v)), str(r.get(c) or ""), re.IGNORECASE):
                    return False
            return True

        matched = [r for r in rows if match(r)]
        if q._mode == "update":
            for r in matched:
                r.update(q._data)
            return matched
        if q._mode == "delete":
            self.tables[q.t] = [r for r in rows if not match(r)]
            return matched
        if q._limit is not None:
            matched = matched[: q._limit]
        return matched


class FakeClusterService:
    """Stand-in for ClusterManagementService that writes to the FakeStore."""

    def __init__(self, store):
        self.store = store
        self.calls = []

    def create_cluster(self, **kw):
        self.calls.append(("create_cluster", kw))
        return self.store.table("seo_clusters").insert({
            "name": kw.get("name"),
            "project_id": kw.get("project_id"),
            "pillar_keyword": kw.get("pillar_keyword"),
            "intent": kw.get("intent"),
            "status": "draft",
            "pillar_status": "planned",
            "pillar_article_id": None,
            "source": kw.get("source"),
            "created_from_article_id": kw.get("created_from_article_id"),
        }).execute().data[0]

    def add_spoke(self, cluster_id, keyword_id, role="spoke", priority=2):
        self.calls.append(("add_spoke", {"cluster_id": cluster_id, "keyword_id": keyword_id, "role": role}))
        return self.store.table("seo_cluster_spokes").insert({
            "cluster_id": cluster_id,
            "keyword_id": keyword_id,
            "role": role,
            "status": "planned",
            "article_id": None,
        }).execute().data[0]

    def set_pillar(self, cluster_id, keyword_id):
        self.calls.append(("set_pillar", {"cluster_id": cluster_id, "keyword_id": keyword_id}))
        for r in self.store.table("seo_cluster_spokes").select().eq("cluster_id", cluster_id).execute().data:
            if r.get("role") == "pillar" and r.get("keyword_id") != keyword_id:
                r["role"] = "spoke"
        self.store.table("seo_cluster_spokes").update({"role": "pillar"}).eq(
            "cluster_id", cluster_id
        ).eq("keyword_id", keyword_id).execute()
        return {}

    def update_spoke(self, spoke_id, **updates):
        self.calls.append(("update_spoke", {"spoke_id": spoke_id, **updates}))
        res = self.store.table("seo_cluster_spokes").update(dict(updates)).eq("id", spoke_id).execute()
        return res.data[0] if res.data else None


class FakeKeywordService:
    def __init__(self, store):
        self.store = store
        self.created = []

    def create_keyword(self, project_id, keyword):
        self.created.append(keyword)
        return self.store.table("seo_keywords").insert({
            "project_id": project_id,
            "keyword": keyword,
            "status": "in_progress",
        }).execute().data[0]


class FakeAnthropic:
    """Returns canned payloads per .create() call (last payload repeats)."""

    def __init__(self, payloads):
        self._p = [payloads] if isinstance(payloads, str) else list(payloads)
        self._i = 0
        self.messages = self

    def create(self, **kw):
        text = self._p[min(self._i, len(self._p) - 1)] if self._p else ""
        self._i += 1
        return SimpleNamespace(
            content=[SimpleNamespace(text=text)],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )


def _svc(article_overrides=None, llm=""):
    store = FakeStore()
    store.tables["brands"] = [{"id": "b1", "organization_id": "org-1"}]
    art = {
        "id": "art-1", "keyword": "gaming slang", "keyword_id": "kw-art",
        "title": "What Is Gaming Slang?", "project_id": "p1", "brand_id": "b1",
        "organization_id": "org-1", "published_url": "https://x.com/gaming-slang",
        "status": "published",
    }
    if article_overrides:
        art.update(article_overrides)
    store.tables["seo_articles"] = [art]
    svc = ClusterBuildService(
        supabase_client=store,
        cluster_service=FakeClusterService(store),
        keyword_service=FakeKeywordService(store),
        anthropic_client=FakeAnthropic(llm),
    )
    svc._track_usage = lambda **kw: None  # keep UsageTracker out of the unit
    return svc, store


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
class TestExpandByEntities:
    def test_template_substitution(self):
        assert ClusterBuildService.expand_by_entities(
            ["Fortnite", "Roblox"], "Common {entity} Gaming Slang"
        ) == ["Common Fortnite Gaming Slang", "Common Roblox Gaming Slang"]

    def test_dedupe_case_insensitive(self):
        assert ClusterBuildService.expand_by_entities(["A", "A", "a"], "{entity} guide") == ["A guide"]

    def test_empty_list(self):
        assert ClusterBuildService.expand_by_entities([], "{entity} guide") == []

    def test_missing_placeholder_raises(self):
        with pytest.raises(ValueError):
            ClusterBuildService.expand_by_entities(["A"], "no placeholder here")


class TestResolveOrgId:
    def test_real_org_passes_through(self):
        svc, _ = _svc()
        assert svc._resolve_org_id("org-xyz", "b1") == "org-xyz"

    def test_all_resolves_from_brand(self):
        svc, _ = _svc()
        assert svc._resolve_org_id("all", "b1") == "org-1"

    def test_all_fails_closed_when_unresolvable(self):
        svc, store = _svc()
        store.tables["brands"] = []
        with pytest.raises(ValueError):
            svc._resolve_org_id("all", "b1")


class TestFindOrCreateKeyword:
    def test_finds_existing_normalized_without_creating(self):
        svc, store = _svc()
        store.tables["seo_keywords"] = [{"id": "k1", "project_id": "p1", "keyword": "Video Games"}]
        got = svc._find_or_create_keyword("p1", "video games")  # different case
        assert got["id"] == "k1"
        assert svc.keyword_service.created == []  # no duplicate row

    def test_creates_when_absent(self):
        svc, _ = _svc()
        made = svc._find_or_create_keyword("p1", "brand new topic")
        assert made["keyword"] == "brand new topic"
        assert "brand new topic" in svc.keyword_service.created

    def test_finds_across_whitespace_and_separator_variants(self):
        # Codex P2#4: collapsed-whitespace variants must not create duplicates.
        svc, store = _svc()
        store.tables["seo_keywords"] = [{"id": "k1", "project_id": "p1", "keyword": "video  games"}]
        got = svc._find_or_create_keyword("p1", "Video Games")  # single space, different case
        assert got["id"] == "k1"
        assert svc.keyword_service.created == []


class TestProposeSpokesLlm:
    def test_parses_json_array(self):
        svc, _ = _svc(llm='["Roblox slang", "Discord slang"]')
        assert svc.propose_spokes_llm("gaming slang", None, 5, "org-1") == ["Roblox slang", "Discord slang"]

    def test_strips_json_fence(self):
        svc, _ = _svc(llm='```json\n["a", "b"]\n```')
        assert svc.propose_spokes_llm("x", None, 5, "org-1") == ["a", "b"]

    def test_garbage_returns_empty(self):
        svc, _ = _svc(llm="sorry, no json here")
        assert svc.propose_spokes_llm("x", None, 5, "org-1") == []


# ---------------------------------------------------------------------------
# plan_cluster_from_article (no writes)
# ---------------------------------------------------------------------------
class TestPlan:
    def test_entity_mode_riser_is_pillar(self):
        svc, _ = _svc()
        plan = svc.plan_cluster_from_article(
            "art-1", "b1", mode="entity",
            entities=["Fortnite", "Roblox"], template="Common {entity} Gaming Slang",
        )
        assert plan["pillar_keyword"] == "gaming slang"
        assert plan["pillar_mode"] == "pillar"
        assert plan["proposed_spokes"] == ["Common Fortnite Gaming Slang", "Common Roblox Gaming Slang"]

    def test_llm_mode_excludes_pillar_collision(self):
        svc, _ = _svc(llm='["gaming slang", "Roblox slang"]')  # first collides with pillar
        plan = svc.plan_cluster_from_article("art-1", "b1", mode="llm")
        assert plan["proposed_spokes"] == ["Roblox slang"]

    def test_parent_pillar_mode_discovers_pillar_and_reserves_riser(self):
        svc, _ = _svc(llm=['{"pillar_keyword": "video game slang"}', '["gaming slang", "Roblox slang"]'])
        plan = svc.plan_cluster_from_article("art-1", "b1", mode="llm", pillar_mode="spoke")
        assert plan["pillar_keyword"] == "video game slang"
        assert plan["pillar_mode"] == "spoke"
        # the riser keyword ("gaming slang") is reserved out of the spokes
        assert plan["proposed_spokes"] == ["Roblox slang"]

    def test_wrong_brand_rejected(self):
        svc, _ = _svc()
        with pytest.raises(ValueError):
            svc.plan_cluster_from_article("art-1", "WRONG", mode="entity",
                                          entities=["A"], template="{entity} x")

    def test_article_without_project_rejected(self):
        svc, _ = _svc({"project_id": None})
        with pytest.raises(ValueError):
            svc.plan_cluster_from_article("art-1", "b1", mode="entity",
                                          entities=["A"], template="{entity} x")


# ---------------------------------------------------------------------------
# create_cluster_from_plan (writes, idempotent)
# ---------------------------------------------------------------------------
class TestCreate:
    def test_new_cluster_riser_pillar(self):
        svc, store = _svc()
        res = svc.create_cluster_from_plan(
            "art-1", "gaming slang", ["Roblox slang", "Fortnite slang"], "b1", pillar_mode="pillar"
        )
        assert res["reused_cluster"] is False
        assert res["pillar_article_id"] == "art-1"
        assert {e["keyword"] for e in res["spokes_created"]} == {"Roblox slang", "Fortnite slang"}

        clu = store.tables["seo_clusters"][0]
        assert clu["source"] == "cluster_builder"
        assert clu["created_from_article_id"] == "art-1"
        assert clu["pillar_article_id"] == "art-1"

        pillars = [s for s in store.tables["seo_cluster_spokes"] if s["role"] == "pillar"]
        assert len(pillars) == 1
        # live winner linked as the pillar with a published (NOT 'writing') status
        assert pillars[0]["article_id"] == "art-1"
        assert pillars[0]["status"] == "published"

    def test_rerun_is_idempotent(self):
        svc, store = _svc()
        svc.create_cluster_from_plan("art-1", "gaming slang", ["Roblox slang", "Fortnite slang"], "b1")
        res2 = svc.create_cluster_from_plan("art-1", "gaming slang", ["Roblox slang", "Fortnite slang"], "b1")

        assert res2["reused_cluster"] is True
        assert res2["spokes_created"] == []
        assert {e["keyword"] for e in res2["spokes_skipped"]} == {"Roblox slang", "Fortnite slang"}
        # no duplicate clusters / spokes / keywords
        assert len(store.tables["seo_clusters"]) == 1
        assert len([s for s in store.tables["seo_cluster_spokes"] if s["role"] == "spoke"]) == 2
        kws = [k["keyword"] for k in store.tables["seo_keywords"]]
        assert kws.count("Roblox slang") == 1

    def test_partial_failure_skips_one_keeps_rest(self):
        svc, _ = _svc()
        orig = svc._find_or_create_keyword

        def boom(project_id, keyword):
            if keyword == "BadKW":
                raise RuntimeError("embed failed")
            return orig(project_id, keyword)

        svc._find_or_create_keyword = boom
        res = svc.create_cluster_from_plan("art-1", "gaming slang", ["GoodKW", "BadKW"], "b1")
        assert [e["keyword"] for e in res["spokes_created"]] == ["GoodKW"]
        assert [e["keyword"] for e in res["spokes_failed"]] == ["BadKW"]

    def test_parent_pillar_mode_links_riser_as_spoke(self):
        svc, store = _svc()
        res = svc.create_cluster_from_plan(
            "art-1", "video game slang", ["Roblox slang"], "b1", pillar_mode="spoke"
        )
        assert res["pillar_mode"] == "spoke"
        assert res["pillar_article_id"] is None
        assert {e["keyword"] for e in res["spokes_created"]} == {"Roblox slang"}

        spokes = store.tables["seo_cluster_spokes"]
        pillar = [s for s in spokes if s["role"] == "pillar"][0]
        assert pillar["article_id"] is None  # discovered pillar has no article yet
        # the rising article is linked as a spoke
        linked = [s for s in spokes if s["role"] == "spoke" and s.get("article_id") == "art-1"]
        assert len(linked) == 1
        assert linked[0]["status"] == "published"

    def test_caps_and_warns_beyond_max_spokes(self):
        svc, _ = _svc()
        many = [f"spoke topic {i}" for i in range(20)]
        res = svc.create_cluster_from_plan("art-1", "gaming slang", many, "b1")
        assert len(res["spokes_created"]) == ClusterBuildService.MAX_SPOKES
        assert any("Capped" in w for w in res["warnings"])

    def test_does_not_hijack_a_manual_cluster_with_same_name(self):
        # Codex P1: a same-named hand-built cluster must NOT be reused/demoted.
        svc, store = _svc()
        store.tables["seo_clusters"] = [{
            "id": "manual-1", "project_id": "p1", "name": "gaming slang",
            "source": None, "pillar_keyword": "gaming slang", "pillar_article_id": None,
        }]
        res = svc.create_cluster_from_plan("art-1", "gaming slang", ["Roblox slang"], "b1")
        assert res["reused_cluster"] is False
        assert res["cluster_id"] != "manual-1"
        # the manual cluster is untouched; the builder cluster took a distinct name
        new_clu = next(c for c in store.tables["seo_clusters"] if c["id"] == res["cluster_id"])
        assert new_clu["source"] == "cluster_builder"
        assert new_clu["name"] == "gaming slang (cluster builder)"

    def test_non_duplicate_spoke_error_surfaces_as_failed(self):
        # add_spoke that fails for a non-conflict reason must be reported, not
        # swallowed as "already exists".
        svc, store = _svc()
        real_add = svc.cluster_service.add_spoke

        def flaky(cluster_id, keyword_id, role="spoke", priority=2):
            kw = next((k for k in store.tables["seo_keywords"] if k["id"] == keyword_id), {})
            if kw.get("keyword") == "Bad Spoke":
                raise RuntimeError("centroid update exploded")
            return real_add(cluster_id, keyword_id, role=role, priority=priority)

        svc.cluster_service.add_spoke = flaky
        res = svc.create_cluster_from_plan("art-1", "gaming slang", ["Good Spoke", "Bad Spoke"], "b1")
        assert [e["keyword"] for e in res["spokes_created"]] == ["Good Spoke"]
        assert [e["keyword"] for e in res["spokes_failed"]] == ["Bad Spoke"]

    def test_duplicate_spoke_error_treated_as_existing(self):
        # A real UNIQUE conflict (concurrent insert) is tolerated as "already there".
        svc, store = _svc()
        real_add = svc.cluster_service.add_spoke

        def dup(cluster_id, keyword_id, role="spoke", priority=2):
            kw = next((k for k in store.tables["seo_keywords"] if k["id"] == keyword_id), {})
            if kw.get("keyword") == "Racy Spoke":
                real_add(cluster_id, keyword_id, role=role)  # row lands...
                raise RuntimeError("duplicate key value violates unique constraint")
            return real_add(cluster_id, keyword_id, role=role)

        svc.cluster_service.add_spoke = dup
        res = svc.create_cluster_from_plan("art-1", "gaming slang", ["Racy Spoke"], "b1")
        assert [e["keyword"] for e in res["spokes_skipped"]] == ["Racy Spoke"]
        assert res["spokes_failed"] == []

    def test_parent_rebuild_clears_stale_pillar_article(self):
        # Codex P2#2: re-building the same article as a parent-spoke must clear the
        # pillar_article_id set by the earlier riser-as-pillar build.
        svc, store = _svc()
        svc.create_cluster_from_plan("art-1", "gaming slang", ["Roblox slang"], "b1", pillar_mode="pillar")
        clu = store.tables["seo_clusters"][0]
        assert clu["pillar_article_id"] == "art-1"  # riser is the pillar

        svc.create_cluster_from_plan("art-1", "video game slang", ["Fortnite slang"], "b1", pillar_mode="spoke")
        assert clu["pillar_article_id"] is None  # cleared - discovered pillar has no article yet
