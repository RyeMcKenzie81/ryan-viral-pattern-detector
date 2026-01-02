"""
Belief-First Reverse Engineer Pipeline Tests.

Test suite for the belief reverse engineer pipeline:
- Service unit tests (BeliefAnalysisService, ProductContextService)
- Pipeline node tests
- Integration tests

Run with: pytest tests/test_belief_reverse_engineer.py -v
"""

import pytest
from uuid import UUID, uuid4
from typing import Dict, List, Any

# Service imports
from viraltracker.services.belief_analysis_service import (
    BeliefAnalysisService,
    get_parse_messages_prompt,
    get_layer_classifier_prompt,
    get_draft_canvas_prompt,
)
from viraltracker.services.models import (
    EvidenceStatus,
    BeliefLayer,
    ProofType,
    ConstraintType,
    RiskFlagType,
    RiskSeverity,
    MessageClassification,
    ProductContext,
)
from viraltracker.pipelines.states import BeliefReverseEngineerState


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def belief_service():
    """Create BeliefAnalysisService instance."""
    return BeliefAnalysisService()


@pytest.fixture
def sample_messages():
    """Sample marketing messages for testing."""
    return [
        "Boba without the sugar crash",
        "30g of protein that actually tastes like dessert",
        "Finally, a way to enjoy boba guilt-free",
        "The real reason diets fail isn't willpower - it's blood sugar",
    ]


@pytest.fixture
def sample_product_context():
    """Sample product context dict."""
    return {
        "product_id": str(uuid4()),
        "name": "Protein Boba",
        "category": "health_food",
        "format": "drink",
        "macros": {
            "protein_g": 30,
            "sugar_g": 2,
            "calories": 180,
        },
        "ingredients": [
            {"name": "whey protein", "purpose": "protein source"},
            {"name": "tapioca pearls", "purpose": "boba texture"},
        ],
        "allowed_claims": ["high protein", "low sugar"],
        "disallowed_claims": ["cures diabetes", "treats obesity"],
        "promise_boundary_default": "Does not claim medical benefits",
        "mechanisms": [],
        "proof_assets": [],
        "contraindications": [],
    }


@pytest.fixture
def sample_classifications():
    """Sample message classifications."""
    return [
        {
            "message": "Boba without the sugar crash",
            "primary_layer": "EXPRESSION",
            "secondary_layers": [],
            "confidence": 0.8,
            "detected_topics": ["boba", "sugar"],
            "triggers_compliance_mode": False,
        },
        {
            "message": "30g of protein that actually tastes like dessert",
            "primary_layer": "BENEFIT",
            "secondary_layers": ["EXPRESSION"],
            "confidence": 0.7,
            "detected_topics": ["protein"],
            "triggers_compliance_mode": False,
        },
        {
            "message": "The real reason diets fail isn't willpower - it's blood sugar",
            "primary_layer": "UMP_SEED",
            "secondary_layers": [],
            "confidence": 0.85,
            "detected_topics": ["sugar"],
            "triggers_compliance_mode": False,
        },
    ]


# ============================================================================
# BeliefAnalysisService Unit Tests
# ============================================================================

class TestBeliefAnalysisService:
    """Unit tests for BeliefAnalysisService."""

    @pytest.mark.asyncio
    async def test_parse_messages_basic(self, belief_service, sample_messages):
        """Test that parse_messages returns structured data."""
        parsed = await belief_service.parse_messages(
            messages=sample_messages,
            product_name="Protein Boba",
            product_category="health_food",
        )

        assert isinstance(parsed, list)
        assert len(parsed) == len(sample_messages)

        for p in parsed:
            assert "message" in p
            assert "detected_topics" in p
            assert isinstance(p["detected_topics"], list)

    @pytest.mark.asyncio
    async def test_parse_messages_detects_topics(self, belief_service):
        """Test that parse_messages detects relevant topics."""
        messages = ["Boba without sugar crash"]
        parsed = await belief_service.parse_messages(
            messages=messages,
            product_name="Test",
            product_category="beverage",
        )

        assert len(parsed) == 1
        topics = parsed[0]["detected_topics"]
        assert "boba" in topics or "sugar" in topics

    @pytest.mark.asyncio
    async def test_classify_message_layer_ump(self, belief_service):
        """Test UMP seed detection."""
        parsed_msg = {
            "message": "The real reason diets fail isn't willpower",
            "detected_topics": ["diet"],
        }

        classification = await belief_service.classify_message_layer(
            parsed_message=parsed_msg,
            product_category="health_food",
        )

        assert classification.primary_layer == BeliefLayer.UMP_SEED

    @pytest.mark.asyncio
    async def test_classify_message_layer_benefit(self, belief_service):
        """Test benefit detection."""
        parsed_msg = {
            "message": "Finally enjoy your favorite treats without guilt",
            "detected_topics": [],
        }

        classification = await belief_service.classify_message_layer(
            parsed_message=parsed_msg,
            product_category="health_food",
        )

        assert classification.primary_layer == BeliefLayer.BENEFIT

    @pytest.mark.asyncio
    async def test_classify_message_compliance_trigger(self, belief_service):
        """Test that medical/drug references trigger compliance mode."""
        parsed_msg = {
            "message": "Works better than Ozempic for weight loss",
            "detected_topics": ["glp-1"],
        }

        classification = await belief_service.classify_message_layer(
            parsed_message=parsed_msg,
            product_category="supplement",
        )

        assert classification.triggers_compliance_mode is True

    @pytest.mark.asyncio
    async def test_assemble_draft_canvas(
        self, belief_service, sample_classifications, sample_product_context
    ):
        """Test draft canvas assembly."""
        result = await belief_service.assemble_draft_canvas(
            classifications=sample_classifications,
            product_context=sample_product_context,
            format_hint="ad",
        )

        assert "canvas" in result
        assert "research_needed" in result
        assert "proof_needed" in result
        assert "trace_map" in result

        canvas = result["canvas"]
        assert "research_canvas" in canvas
        assert "belief_canvas" in canvas

    def test_run_integrity_checks_draft_mode(
        self, belief_service, sample_product_context
    ):
        """Test integrity checks in draft mode."""
        canvas = {
            "research_canvas": {},
            "belief_canvas": {
                "unique_mechanism": {"ump": {}, "ums": {}},
                "progress_justification": {"benefits": {}, "features": []},
            },
        }

        results = belief_service.run_integrity_checks(
            canvas=canvas,
            draft_mode=True,
        )

        assert isinstance(results, list)
        assert len(results) > 0

        # In draft mode, empty research should pass with warning
        research_check = next(
            r for r in results if r["check"] == "research_precedes_framing"
        )
        assert research_check["passed"] is True
        assert "warning" in research_check.get("severity", "")

    def test_run_integrity_checks_features_before_benefits(self, belief_service):
        """Test that features before benefits fails integrity."""
        canvas = {
            "research_canvas": {},
            "belief_canvas": {
                "unique_mechanism": {"ump": {}, "ums": {}},
                "progress_justification": {
                    "benefits": {},  # Empty
                    "features": ["Feature 1"],  # Has features
                },
            },
        }

        results = belief_service.run_integrity_checks(
            canvas=canvas,
            draft_mode=True,
        )

        features_check = next(
            r for r in results if r["check"] == "features_after_benefits"
        )
        assert features_check["passed"] is False

    @pytest.mark.asyncio
    async def test_detect_risks_medical_claim(self, belief_service):
        """Test detection of medical claims."""
        canvas = {
            "belief_canvas": {
                "unique_mechanism": {
                    "ump": {
                        "reframed_root_cause": "This treats the underlying disease"
                    }
                }
            }
        }

        risks = await belief_service.detect_risks(
            canvas=canvas,
            product_context={},
        )

        assert len(risks) > 0
        medical_risks = [r for r in risks if r.type == RiskFlagType.MEDICAL_CLAIM]
        assert len(medical_risks) > 0

    @pytest.mark.asyncio
    async def test_detect_risks_drug_reference(self, belief_service):
        """Test detection of drug references."""
        canvas = {
            "belief_canvas": {
                "expression": {
                    "core_hook": "Better than Ozempic for weight management"
                }
            }
        }

        risks = await belief_service.detect_risks(
            canvas=canvas,
            product_context={},
        )

        drug_risks = [r for r in risks if r.type == RiskFlagType.DRUG_REFERENCE]
        assert len(drug_risks) > 0

    def test_render_markdown_canvas(self, belief_service):
        """Test markdown canvas rendering."""
        canvas = {
            "research_canvas": {
                "market_context": {"category": "health_food"},
                "observed_pain": {"symptoms_physical": ["bloating"]},
            },
            "belief_canvas": {
                "belief_context": {"promise_boundary": "No medical claims"},
                "unique_mechanism": {
                    "ump": {"reframed_root_cause": "Blood sugar spikes"},
                    "ums": {},
                },
                "persona_filter": {"jtbd": {}, "constraints": {}},
                "progress_justification": {"benefits": {}, "features": []},
                "proof_stack": {},
                "expression": {"core_hook": "Boba without the crash"},
            },
        }

        markdown = belief_service.render_markdown_canvas(
            canvas=canvas,
            product_name="Protein Boba",
        )

        assert "# Belief-First Master Canvas" in markdown
        assert "Protein Boba" in markdown
        assert "health_food" in markdown
        assert "Blood sugar spikes" in markdown


# ============================================================================
# State Class Tests
# ============================================================================

class TestBeliefReverseEngineerState:
    """Tests for BeliefReverseEngineerState dataclass."""

    def test_state_initialization(self):
        """Test state initializes with defaults."""
        state = BeliefReverseEngineerState(
            product_id=uuid4(),
            messages=["Test message"],
        )

        assert state.draft_mode is True
        assert state.research_mode is False
        assert state.current_step == "pending"
        assert state.error is None
        assert len(state.trace_map) == 0
        assert len(state.risk_flags) == 0

    def test_state_with_research_mode(self):
        """Test state with research mode enabled."""
        state = BeliefReverseEngineerState(
            product_id=uuid4(),
            messages=["Test message"],
            draft_mode=False,
            research_mode=True,
            subreddits=["nutrition", "fitness"],
            search_terms=["protein", "boba"],
        )

        assert state.research_mode is True
        assert len(state.subreddits) == 2
        assert len(state.search_terms) == 2


# ============================================================================
# Model Tests
# ============================================================================

class TestBeliefModels:
    """Tests for belief-related Pydantic models."""

    def test_evidence_status_enum(self):
        """Test EvidenceStatus enum values."""
        assert EvidenceStatus.OBSERVED.value == "observed"
        assert EvidenceStatus.INFERRED.value == "inferred"
        assert EvidenceStatus.HYPOTHESIS.value == "hypothesis"

    def test_belief_layer_enum(self):
        """Test BeliefLayer enum values."""
        assert BeliefLayer.EXPRESSION.value == "EXPRESSION"
        assert BeliefLayer.UMP_SEED.value == "UMP_SEED"
        assert BeliefLayer.UMS_SEED.value == "UMS_SEED"
        assert BeliefLayer.BENEFIT.value == "BENEFIT"

    def test_constraint_type_enum(self):
        """Test ConstraintType enum values."""
        assert ConstraintType.TIME.value == "time"
        assert ConstraintType.MONEY.value == "money"
        assert ConstraintType.ENERGY.value == "energy"
        assert ConstraintType.IDENTITY.value == "identity"

    def test_message_classification_model(self):
        """Test MessageClassification model."""
        classification = MessageClassification(
            message="Test message",
            primary_layer=BeliefLayer.EXPRESSION,
            secondary_layers=[BeliefLayer.BENEFIT],
            confidence=0.8,
            detected_topics=["topic1"],
            triggers_compliance_mode=False,
        )

        assert classification.message == "Test message"
        assert classification.primary_layer == BeliefLayer.EXPRESSION
        assert len(classification.secondary_layers) == 1
        assert classification.confidence == 0.8


# ============================================================================
# Prompt Tests
# ============================================================================

class TestPrompts:
    """Tests for LLM prompt getters."""

    def test_parse_messages_prompt_exists(self):
        """Test that parse messages prompt is defined."""
        prompt = get_parse_messages_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 100
        assert "topics" in prompt.lower()

    def test_layer_classifier_prompt_exists(self):
        """Test that layer classifier prompt is defined."""
        prompt = get_layer_classifier_prompt()
        assert isinstance(prompt, str)
        assert "EXPRESSION" in prompt
        assert "UMP_SEED" in prompt

    def test_draft_canvas_prompt_exists(self):
        """Test that draft canvas prompt is defined."""
        prompt = get_draft_canvas_prompt()
        assert isinstance(prompt, str)
        assert "Belief Context" in prompt
        assert "Unique Mechanism" in prompt


# ============================================================================
# Integration Tests (Placeholder)
# ============================================================================

@pytest.mark.integration
class TestBeliefReverseEngineerIntegration:
    """Integration tests for the full pipeline."""

    @pytest.mark.skip(reason="Requires database and API connections")
    @pytest.mark.asyncio
    async def test_full_draft_mode_pipeline(self):
        """Test running the full pipeline in draft mode."""
        # This test requires actual database connections
        # and would be run in CI with proper fixtures
        pass

    @pytest.mark.skip(reason="Requires database and API connections")
    @pytest.mark.asyncio
    async def test_full_research_mode_pipeline(self):
        """Test running the full pipeline in research mode."""
        # This test requires actual database and Reddit API connections
        pass
