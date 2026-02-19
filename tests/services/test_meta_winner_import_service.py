"""
Tests for MetaWinnerImportService — import, URL matching, idempotency, reward,
element tag extraction, best-effort embedding/exemplar, evolution compatibility.

All database calls are mocked — no real DB or API connections needed.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from uuid import UUID, uuid4

BRAND_ID = UUID("00000000-0000-0000-0000-000000000001")
PRODUCT_ID = UUID("00000000-0000-0000-0000-000000000002")
META_AD_ID = "123456789"
META_AD_ACCOUNT_ID = "act_111"


@pytest.fixture
def import_service():
    """Create a MetaWinnerImportService with mocked Supabase client."""
    with patch("viraltracker.core.database.get_supabase_client") as mock_db:
        mock_db.return_value = MagicMock()
        from viraltracker.services.meta_winner_import_service import MetaWinnerImportService
        service = MetaWinnerImportService()
        service.supabase = MagicMock()
        yield service


def _mock_chain(mock, data=None, count=None):
    """Helper to set up Supabase chain returns: .select().eq().execute()."""
    chain = MagicMock()
    result = MagicMock()
    result.data = data
    result.count = count
    chain.execute.return_value = result
    # Make all filter methods return the same chain
    for method in ["select", "eq", "neq", "in_", "gte", "lte", "is_", "not_",
                    "order", "limit", "insert", "update", "upsert", "delete"]:
        getattr(chain, method, MagicMock()).return_value = chain
    chain.not_.is_.return_value = chain
    return chain


# ============================================================================
# TestFindImportCandidates
# ============================================================================

class TestFindImportCandidates:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_perf_data(self, import_service):
        import_service.supabase.table.return_value = _mock_chain(
            import_service.supabase, data=[]
        )
        result = await import_service.find_import_candidates(BRAND_ID)
        assert result == []

    @pytest.mark.asyncio
    async def test_excludes_already_imported(self, import_service):
        """Ads that already have is_imported=True in generated_ads should be excluded."""
        perf_chain = _mock_chain(import_service.supabase, data=[
            {"meta_ad_id": META_AD_ID, "meta_ad_account_id": META_AD_ACCOUNT_ID,
             "impressions": 5000, "spend": 200, "link_ctr": 0.03,
             "conversion_rate": 0.02, "roas": 3.0, "campaign_objective": "CONVERSIONS",
             "is_video": False, "thumbnail_url": "http://example.com/img.jpg",
             "ad_name": "Test Ad"},
        ])

        imported_chain = _mock_chain(import_service.supabase, data=[
            {"meta_ad_id": META_AD_ID},  # Already imported
        ])

        mapped_chain = _mock_chain(import_service.supabase, data=[])

        call_count = [0]
        def table_side_effect(name):
            call_count[0] += 1
            if name == "meta_ads_performance":
                return perf_chain
            elif name == "generated_ads":
                return imported_chain
            elif name == "meta_ad_mapping":
                return mapped_chain
            return _mock_chain(import_service.supabase, data=[])

        import_service.supabase.table.side_effect = table_side_effect

        with patch("viraltracker.services.meta_winner_import_service.MetaWinnerImportService.match_offer_variant",
                    new_callable=AsyncMock, return_value=[]):
            with patch("viraltracker.services.creative_genome_service.CreativeGenomeService._load_baselines",
                        return_value={"p25_ctr": 0.005, "p75_ctr": 0.02, "p25_conversion_rate": 0.005,
                                      "p75_conversion_rate": 0.03, "p25_roas": 0.5, "p75_roas": 3.0}):
                result = await import_service.find_import_candidates(BRAND_ID)

        assert len(result) == 0  # excluded because already imported


# ============================================================================
# TestMatchOfferVariant
# ============================================================================

class TestMatchOfferVariant:
    @pytest.mark.asyncio
    async def test_no_destinations_returns_empty(self, import_service):
        import_service.supabase.table.return_value = _mock_chain(
            import_service.supabase, data=[]
        )
        result = await import_service.match_offer_variant(BRAND_ID, META_AD_ID)
        assert result == []

    @pytest.mark.asyncio
    async def test_exact_match_preferred_over_canonical(self, import_service):
        """When both exact and canonical match, exact appears first."""
        variant_id = str(uuid4())
        product_id = str(PRODUCT_ID)

        dest_chain = _mock_chain(import_service.supabase, data=[
            {"original_url": "https://example.com/offer?utm_source=fb",
             "canonical_url": "https://example.com/offer"},
        ])
        products_chain = _mock_chain(import_service.supabase, data=[
            {"id": product_id},
        ])
        variants_chain = _mock_chain(import_service.supabase, data=[
            {"id": variant_id, "product_id": product_id,
             "variant_name": "Test Variant",
             "landing_page_url": "https://example.com/offer?utm_source=fb"},
        ])

        def table_side(name):
            if name == "meta_ad_destinations":
                return dest_chain
            elif name == "products":
                return products_chain
            elif name == "product_offer_variants":
                return variants_chain
            return _mock_chain(import_service.supabase, data=[])

        import_service.supabase.table.side_effect = table_side

        result = await import_service.match_offer_variant(BRAND_ID, META_AD_ID)
        assert len(result) >= 1
        assert result[0]["match_type"] == "exact"

    @pytest.mark.asyncio
    async def test_no_match_returns_empty_list(self, import_service):
        """URLs that don't match any variant return empty list."""
        dest_chain = _mock_chain(import_service.supabase, data=[
            {"original_url": "https://unrelated.com/page",
             "canonical_url": "https://unrelated.com/page"},
        ])
        products_chain = _mock_chain(import_service.supabase, data=[
            {"id": str(PRODUCT_ID)},
        ])
        variants_chain = _mock_chain(import_service.supabase, data=[
            {"id": str(uuid4()), "product_id": str(PRODUCT_ID),
             "variant_name": "Variant A",
             "landing_page_url": "https://example.com/totally-different"},
        ])

        def table_side(name):
            if name == "meta_ad_destinations":
                return dest_chain
            elif name == "products":
                return products_chain
            elif name == "product_offer_variants":
                return variants_chain
            return _mock_chain(import_service.supabase, data=[])

        import_service.supabase.table.side_effect = table_side
        result = await import_service.match_offer_variant(BRAND_ID, META_AD_ID)
        assert result == []


# ============================================================================
# TestImportMetaWinner
# ============================================================================

class TestImportMetaWinner:
    @pytest.mark.asyncio
    async def test_full_import_creates_all_records(self, import_service):
        """Full import flow creates ad_run, generated_ad, mapping, reward."""
        # Mock idempotency check — not yet imported
        gen_ads_check = _mock_chain(import_service.supabase, data=[])
        # Mock image check
        assets_chain = _mock_chain(import_service.supabase, data=[
            {"storage_path": "meta-ad-assets/test.jpg", "status": "downloaded"},
        ])
        # Mock ad copy
        copy_chain = _mock_chain(import_service.supabase, data=[
            {"headline": "Test", "body_text": "Body", "description": "Desc"},
        ])
        # Mock destination URL
        dest_chain = _mock_chain(import_service.supabase, data=[
            {"original_url": "https://example.com/offer"},
        ])
        # Mock performance data
        perf_chain = _mock_chain(import_service.supabase, data=[
            {"impressions": 5000, "spend": 200, "link_ctr": 0.03,
             "conversion_rate": 0.02, "roas": 3.0, "campaign_objective": "CONVERSIONS",
             "meta_campaign_id": "camp_1"},
        ])
        # Mock ad_run insert
        ad_run_chain = _mock_chain(import_service.supabase, data=[
            {"id": str(uuid4())},
        ])
        # Mock generated_ad insert
        gen_ad_chain = _mock_chain(import_service.supabase, data=[
            {"id": str(uuid4())},
        ])
        # Mock mapping insert
        mapping_chain = _mock_chain(import_service.supabase, data=[{}])
        # Mock reward insert
        reward_chain = _mock_chain(import_service.supabase, data=[{}])

        call_log = []
        def table_side(name):
            call_log.append(name)
            if name == "generated_ads" and len([c for c in call_log if c == "generated_ads"]) == 1:
                return gen_ads_check  # First call: idempotency check
            elif name == "meta_ad_assets":
                return assets_chain
            elif name == "meta_ads_ad_copy":
                return copy_chain
            elif name == "meta_ad_destinations":
                return dest_chain
            elif name == "meta_ads_performance":
                return perf_chain
            elif name == "ad_runs":
                return ad_run_chain
            elif name == "generated_ads":
                return gen_ad_chain
            elif name == "meta_ad_mapping":
                return mapping_chain
            elif name == "creative_element_rewards":
                return reward_chain
            return _mock_chain(import_service.supabase, data=[])

        import_service.supabase.table.side_effect = table_side

        # Mock _detect_canvas_size and _download_image_bytes
        import_service._detect_canvas_size = AsyncMock(return_value="1080x1080px")
        import_service._download_image_bytes = AsyncMock(return_value=None)

        with patch("viraltracker.services.creative_genome_service.CreativeGenomeService._load_baselines",
                    return_value={"p25_ctr": 0.005, "p75_ctr": 0.02, "p25_conversion_rate": 0.005,
                                  "p75_conversion_rate": 0.03, "p25_roas": 0.5, "p75_roas": 3.0}):
            result = await import_service.import_meta_winner(
                brand_id=BRAND_ID,
                meta_ad_id=META_AD_ID,
                product_id=PRODUCT_ID,
                meta_ad_account_id=META_AD_ACCOUNT_ID,
                extract_element_tags=False,  # skip Gemini call for unit test
            )

        assert result["status"] == "imported"
        assert result["generated_ad_id"] is not None


# ============================================================================
# TestIdempotency
# ============================================================================

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_double_import_returns_already_imported(self, import_service):
        existing_id = str(uuid4())
        import_service.supabase.table.return_value = _mock_chain(
            import_service.supabase, data=[{"id": existing_id}]
        )

        result = await import_service.import_meta_winner(
            brand_id=BRAND_ID,
            meta_ad_id=META_AD_ID,
            product_id=PRODUCT_ID,
            meta_ad_account_id=META_AD_ACCOUNT_ID,
        )

        assert result["status"] == "already_imported"
        assert result["generated_ad_id"] == existing_id


# ============================================================================
# TestElementTagExtraction
# ============================================================================

class TestElementTagExtraction:
    @pytest.mark.asyncio
    async def test_extract_tags_returns_required_keys(self, import_service):
        """Element tag extraction should return all required keys."""
        mock_response = '{"hook_type": "social_proof", "template_category": "Testimonial", "awareness_stage": "solution_aware", "visual_style": "clean minimal"}'

        with patch("viraltracker.services.gemini_service.GeminiService") as mock_gemini_cls:
            mock_gemini = MagicMock()
            mock_gemini.analyze_image = AsyncMock(return_value=mock_response)
            mock_gemini_cls.return_value = mock_gemini

            tags = await import_service.extract_element_tags(b"fake_image_data", "Test copy")

        assert tags["hook_type"] == "social_proof"
        assert tags["template_category"] == "Testimonial"
        assert tags["content_source"] == "recreate_template"  # D2
        assert tags["import_source"] == "meta_import"  # D2
        assert tags["extraction_method"] == "ai_import"


# ============================================================================
# TestRewardComputation
# ============================================================================

class TestRewardComputation:
    @pytest.mark.asyncio
    async def test_compute_reward_inserts_score(self, import_service):
        """Reward computation should insert into creative_element_rewards."""
        gen_ad_id = str(uuid4())
        perf_chain = _mock_chain(import_service.supabase, data=[
            {"impressions": 5000, "spend": 200, "link_ctr": 0.03,
             "conversion_rate": 0.02, "roas": 3.0, "campaign_objective": "CONVERSIONS",
             "meta_campaign_id": "camp_1"},
        ])
        reward_chain = _mock_chain(import_service.supabase, data=[])

        def table_side(name):
            if name == "meta_ads_performance":
                return perf_chain
            elif name == "creative_element_rewards":
                return reward_chain
            return _mock_chain(import_service.supabase, data=[])

        import_service.supabase.table.side_effect = table_side

        with patch("viraltracker.services.creative_genome_service.CreativeGenomeService._load_baselines",
                    return_value={"p25_ctr": 0.005, "p75_ctr": 0.02, "p25_conversion_rate": 0.005,
                                  "p75_conversion_rate": 0.03, "p25_roas": 0.5, "p75_roas": 3.0}):
            result = await import_service.compute_reward(BRAND_ID, META_AD_ID, gen_ad_id)

        assert "reward_score" in result
        assert 0 <= result["reward_score"] <= 1


# ============================================================================
# TestGetWinnersByVariant
# ============================================================================

class TestGetWinnersByVariant:
    @pytest.mark.asyncio
    async def test_groups_by_variant_id(self, import_service):
        """Winners should be grouped by offer_variant_id."""
        variant_a = str(uuid4())
        variant_b = str(uuid4())

        rewards_chain = _mock_chain(import_service.supabase, data=[
            {"generated_ad_id": "ad1", "reward_score": 0.8, "reward_components": {}},
            {"generated_ad_id": "ad2", "reward_score": 0.7, "reward_components": {}},
        ])
        ads_chain = _mock_chain(import_service.supabase, data=[
            {"id": "ad1", "storage_path": "p1", "hook_text": "h1", "final_status": "approved",
             "offer_variant_id": variant_a, "canvas_size": "1080x1080px",
             "is_imported": True, "meta_ad_id": "m1", "element_tags": {}},
            {"id": "ad2", "storage_path": "p2", "hook_text": "h2", "final_status": "approved",
             "offer_variant_id": variant_b, "canvas_size": "1080x1350px",
             "is_imported": False, "meta_ad_id": None, "element_tags": {}},
        ])

        def table_side(name):
            if name == "creative_element_rewards":
                return rewards_chain
            elif name == "generated_ads":
                return ads_chain
            return _mock_chain(import_service.supabase, data=[])

        import_service.supabase.table.side_effect = table_side

        result = await import_service.get_winners_by_variant(BRAND_ID)
        assert variant_a in result
        assert variant_b in result
        assert len(result[variant_a]) == 1
        assert len(result[variant_b]) == 1


# ============================================================================
# TestEvolutionCompatibility
# ============================================================================

class TestEvolutionCompatibility:
    def test_imported_ad_element_tags_have_extraction_method(self, import_service):
        """Imported ads should have extraction_method=ai_import in element_tags."""
        # This is validated by the extract_element_tags method always setting it
        import asyncio
        mock_response = '{"hook_type": "curiosity_gap", "template_category": "Product-Focus", "awareness_stage": "problem_aware"}'

        with patch("viraltracker.services.gemini_service.GeminiService") as mock_cls:
            mock_gemini = MagicMock()
            mock_gemini.analyze_image = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_gemini

            tags = asyncio.get_event_loop().run_until_complete(
                import_service.extract_element_tags(b"data")
            )

        assert tags["extraction_method"] == "ai_import"
        # WinnerEvolutionService checks this to force recreate_template
        assert tags["content_source"] == "recreate_template"


# ============================================================================
# TestBestEffortEmbedding
# ============================================================================

class TestBestEffortEmbedding:
    @pytest.mark.asyncio
    async def test_embedding_failure_still_imports(self, import_service):
        """Visual embedding failure should not prevent import."""
        # Setup basic mocks for successful import
        gen_ads_check = _mock_chain(import_service.supabase, data=[])
        assets_chain = _mock_chain(import_service.supabase, data=[
            {"storage_path": "meta-ad-assets/test.jpg", "status": "downloaded"},
        ])
        copy_chain = _mock_chain(import_service.supabase, data=[])
        dest_chain = _mock_chain(import_service.supabase, data=[])
        perf_chain = _mock_chain(import_service.supabase, data=[
            {"impressions": 1000, "spend": 50, "link_ctr": 0.02,
             "conversion_rate": 0.01, "roas": 2.0, "campaign_objective": "CONVERSIONS",
             "meta_campaign_id": "camp_1"},
        ])
        ad_run_chain = _mock_chain(import_service.supabase, data=[{"id": str(uuid4())}])
        gen_ad_chain = _mock_chain(import_service.supabase, data=[{"id": str(uuid4())}])
        mapping_chain = _mock_chain(import_service.supabase, data=[{}])
        reward_chain = _mock_chain(import_service.supabase, data=[{}])

        call_log = []
        def table_side(name):
            call_log.append(name)
            if name == "generated_ads" and call_log.count("generated_ads") == 1:
                return gen_ads_check
            elif name == "meta_ad_assets":
                return assets_chain
            elif name == "meta_ads_ad_copy":
                return copy_chain
            elif name == "meta_ad_destinations":
                return dest_chain
            elif name == "meta_ads_performance":
                return perf_chain
            elif name == "ad_runs":
                return ad_run_chain
            elif name == "generated_ads":
                return gen_ad_chain
            elif name == "meta_ad_mapping":
                return mapping_chain
            elif name == "creative_element_rewards":
                return reward_chain
            return _mock_chain(import_service.supabase, data=[])

        import_service.supabase.table.side_effect = table_side
        import_service._detect_canvas_size = AsyncMock(return_value="1080x1080px")
        # Return bytes so embedding is attempted
        import_service._download_image_bytes = AsyncMock(return_value=b"fake_image")

        with patch("viraltracker.services.creative_genome_service.CreativeGenomeService._load_baselines",
                    return_value={"p25_ctr": 0.005, "p75_ctr": 0.02, "p25_conversion_rate": 0.005,
                                  "p75_conversion_rate": 0.03, "p25_roas": 0.5, "p75_roas": 3.0}):
            # Make embedding raise
            with patch("viraltracker.pipelines.ad_creation_v2.services.visual_descriptor_service.VisualDescriptorService") as mock_vds_cls:
                mock_vds = MagicMock()
                mock_vds.extract_and_store = AsyncMock(side_effect=Exception("API error"))
                mock_vds_cls.return_value = mock_vds

                result = await import_service.import_meta_winner(
                    brand_id=BRAND_ID,
                    meta_ad_id=META_AD_ID,
                    product_id=PRODUCT_ID,
                    meta_ad_account_id=META_AD_ACCOUNT_ID,
                    extract_element_tags=False,
                )

        assert result["status"] == "imported"
        assert any("embedding_failed" in w for w in result.get("warnings", []))


# ============================================================================
# TestBestEffortExemplar
# ============================================================================

class TestBestEffortExemplar:
    @pytest.mark.asyncio
    async def test_exemplar_failure_still_imports(self, import_service):
        """Exemplar marking failure should not prevent import."""
        gen_ads_check = _mock_chain(import_service.supabase, data=[])
        assets_chain = _mock_chain(import_service.supabase, data=[
            {"storage_path": "meta-ad-assets/test.jpg", "status": "downloaded"},
        ])

        call_log = []
        def table_side(name):
            call_log.append(name)
            if name == "generated_ads" and call_log.count("generated_ads") == 1:
                return gen_ads_check
            elif name == "meta_ad_assets":
                return assets_chain
            return _mock_chain(import_service.supabase, data=[
                {"id": str(uuid4()), "impressions": 1000, "spend": 50,
                 "link_ctr": 0.02, "conversion_rate": 0.01, "roas": 2.0,
                 "campaign_objective": "CONVERSIONS", "meta_campaign_id": "camp_1",
                 "storage_path": "x", "status": "ok",
                 "headline": "", "body_text": "", "description": "",
                 "original_url": ""},
            ])

        import_service.supabase.table.side_effect = table_side
        import_service._detect_canvas_size = AsyncMock(return_value="1080x1080px")
        import_service._download_image_bytes = AsyncMock(return_value=None)

        with patch("viraltracker.services.creative_genome_service.CreativeGenomeService._load_baselines",
                    return_value={"p25_ctr": 0.005, "p75_ctr": 0.02, "p25_conversion_rate": 0.005,
                                  "p75_conversion_rate": 0.03, "p25_roas": 0.5, "p75_roas": 3.0}):
            with patch("viraltracker.pipelines.ad_creation_v2.services.exemplar_service.ExemplarService") as mock_es_cls:
                mock_es = MagicMock()
                mock_es.mark_as_exemplar = AsyncMock(side_effect=ValueError("Cap reached"))
                mock_es_cls.return_value = mock_es

                result = await import_service.import_meta_winner(
                    brand_id=BRAND_ID,
                    meta_ad_id=META_AD_ID,
                    product_id=PRODUCT_ID,
                    meta_ad_account_id=META_AD_ACCOUNT_ID,
                    extract_element_tags=False,
                    mark_as_exemplar=True,
                )

        assert result["status"] == "imported"
        assert any("exemplar_failed" in w for w in result.get("warnings", []))
