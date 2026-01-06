"""
Belief Analysis Service for Belief-First Reverse Engineer Pipeline.

Contains all LLM prompts, canvas assembly logic, layer classification,
integrity checks, risk detection, and markdown rendering.

This is the primary business logic service for the belief reverse engineer
pipeline - nodes call into this service for all heavy lifting.
"""

import logging
import json
import re
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

from pydantic_ai import Agent
from viraltracker.core.config import Config
from viraltracker.services.models import (
    ProductContext,
    MessageClassification,
    BeliefLayer,
    BeliefFirstMasterCanvas,
    ResearchCanvas,
    BeliefCanvas,
    IntegrityCheckResult,
    RiskFlag,
    RiskFlagType,
    RiskSeverity,
    TraceItem,
    EvidenceStatus,
    ProofType,
    RedditResearchBundle,
    GapReport,
)

logger = logging.getLogger(__name__)


# =============================================================================
# LLM PROMPTS
# =============================================================================

PARSE_MESSAGES_SYSTEM_PROMPT = """You are analyzing rough marketing messages to extract:
- Topics: What subjects/themes are mentioned (e.g., sugar, boba, GLP-1, bloating, energy)
- Implied audience: Who this message seems to be for
- Implied outcomes: What results/benefits are suggested
- Language cues: Key phrases, terminology, tone markers

Return a JSON object with these fields:
{
    "topics": ["topic1", "topic2"],
    "implied_audience": "description of who this targets",
    "implied_outcomes": ["outcome1", "outcome2"],
    "language_cues": ["phrase1", "phrase2"],
    "tone": "educational|urgent|empathetic|authoritative|casual",
    "awareness_hint": "unaware|problem_aware|solution_aware|product_aware"
}"""


LAYER_CLASSIFIER_SYSTEM_PROMPT = """You are classifying marketing messages into belief-first layers.

The layers are:
- EXPRESSION: Hook, angle, visual metaphor - the creative execution
- UMP_SEED: Seeds the Unique Mechanism Problem - reframes why the problem exists
- UMS_SEED: Seeds the Unique Mechanism Solution - explains why this solution works
- PERSONA_FILTER: Targets a specific persona - uses identity language
- BENEFIT: States a benefit/outcome
- PROOF: Provides evidence, testimonials, data, authority
- OTHER: Doesn't fit clearly into above categories

For each message, identify:
1. Primary layer (the main function)
2. Secondary layers (other layers touched)
3. Confidence (0.0-1.0)
4. Detected topics
5. Whether it triggers compliance mode (medical/drug claims)

Return JSON:
{
    "primary_layer": "EXPRESSION|UMP_SEED|UMS_SEED|PERSONA_FILTER|BENEFIT|PROOF|OTHER",
    "secondary_layers": [],
    "confidence": 0.85,
    "detected_topics": ["topic1"],
    "triggers_compliance_mode": false,
    "reasoning": "Brief explanation"
}"""


DRAFT_CANVAS_SYSTEM_PROMPT = """You are assembling a Belief-First Master Canvas from marketing messages and product data.

Your job is to INFER what belief hierarchy the messages IMPLY - not to judge whether it's correct.

## Canvas Structure (Sections 10-15)

### Section 10: Belief Context
- current_awareness_state: What awareness level is being targeted?
- brand_credibility: Any credibility markers present?
- why_now: Any urgency or timing elements?
- promise_boundary: What is/isn't being promised?

### Section 11: Persona Filter
- jtbd: {functional, emotional, identity} - Jobs to be done implied
- persona_sublayers: {awareness_sophistication, prior_failures, skepticism_level}
- constraints: Which of {time, money, energy, identity, reputation_social, cognitive_load} are implied?
- dominant_constraint: Which constraint is most addressed?

### Section 12: Unique Mechanism
- ump: {
    old_accepted_explanation: What the audience currently believes,
    reframed_root_cause: What the message says is the REAL cause,
    why_past_solutions_failed: Why other approaches didn't work,
    externalized_blame: "It's not your fault" framing,
    missing_1_percent: The key insight they were missing
  }
- ums: {
    macro_solution_logic: One-sentence solution logic,
    micro_mechanism: How it works step by step
  }
- reinterpreted_pain: How the mechanism explains past pain

### Section 13: Progress & Justification
- benefits: {immediate, short_term, long_term}
- features: Only list if present AFTER belief is established

### Section 14: Proof Stack
- solution_efficacy: {present: [...], missing: [...]}
- identity_social: {present: [...], missing: [...]}
- risk_commitment: {present: [...], missing: [...]}

### Section 15: Expression
- primary_angle, core_hook, visual_mechanism_metaphor, formats

## Rules
1. NEVER say "this is wrong" - only describe what IS implied
2. Mark confidence for each inference
3. Note gaps as "research_needed" items
4. Use product_context to fill with OBSERVED data where available

Return the complete belief_canvas JSON."""


RESEARCH_EXTRACTOR_SYSTEM_PROMPT = """You are extracting belief-relevant signals from Reddit posts and comments.

For each piece of content, extract:

1. **Pain signals**: Specific symptoms, frustrations, complaints
   - Physical symptoms with specificity
   - Emotional frustrations
   - Behavioral workarounds they've tried

2. **Solutions attempted**: What they've tried and outcomes
   - What worked briefly
   - What stopped working
   - What never worked
   - Why they think it failed

3. **Pattern signals**: Recurring sequences
   - Triggers (what makes it worse)
   - Improvers (what helps temporarily)
   - Timing patterns

4. **Language bank**: Customer terminology
   - How they describe the problem
   - Words they use for symptoms
   - Phrases that resonate

5. **JTBD candidates**: Desired progress
   - Functional: What they want to accomplish
   - Emotional: How they want to feel
   - Identity: Who they want to become

Return structured JSON:
{
    "extracted_pain": [...],
    "extracted_solutions_attempted": [...],
    "pattern_detection": {
        "triggers": [...],
        "worsens": [...],
        "improves": [...],
        "helps": [...],
        "fails": [...]
    },
    "extracted_language_bank": {
        "symptom_name": ["phrase1", "phrase2"]
    },
    "jtbd_candidates": {
        "functional": [...],
        "emotional": [...],
        "identity": [...]
    }
}"""


CLAIM_RISK_SYSTEM_PROMPT = """You are scanning marketing content for compliance risks.

Flag these risk types:
1. MEDICAL_CLAIM: Claims to treat, cure, prevent disease
2. DRUG_REFERENCE: References to prescription drugs (Ozempic, etc.)
3. OVERPROMISE: Unrealistic guarantees or outcomes
4. AMBIGUITY: Vague claims that could be misinterpreted
5. CONTRADICTION: Claims that conflict with each other
6. PROMISE_BOUNDARY: Claims that exceed what can be delivered

For each risk found, provide:
- type: Risk type from above
- severity: low|medium|high
- reason: Why this is a risk
- suggested_fix: How to reword safely
- affected_fields: Which canvas fields are affected

Return JSON array of risk flags."""


# =============================================================================
# BELIEF ANALYSIS SERVICE
# =============================================================================

class BeliefAnalysisService:
    """
    Service for belief-first reverse engineering analysis.

    Provides methods for:
    - Message parsing and layer classification
    - Canvas assembly from messages + product context
    - Research extraction from Reddit data
    - Integrity validation
    - Risk detection
    - Markdown rendering
    """

    def __init__(self, llm_service=None):
        """
        Initialize with optional LLM service injection.

        Args:
            llm_service: LLM service for prompts (Sonnet/Opus)
        """
        self.llm_service = llm_service

    # =========================================================================
    # MESSAGE PARSING
    # =========================================================================

    async def parse_messages(
        self,
        messages: List[str],
        product_name: str = "",
        product_category: str = "",
        format_hint: Optional[str] = None,
        persona_hint: Optional[str] = None,
        llm_response: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """
        Parse raw messages to extract topics, audience, outcomes, language cues.

        Args:
            messages: List of raw message strings
            product_name: Product name for context
            product_category: Product category for context
            format_hint: Optional format hint (ad, landing_page, etc.)
            persona_hint: Optional persona hint
            llm_response: Pre-computed LLM response (for testing)

        Returns:
            List of parsed message dicts
        """
        parsed = []

        for message in messages:
            if llm_response:
                parsed.append({
                    "message": message,
                    **llm_response
                })
            else:
                # Default parsing without LLM (rule-based fallback)
                parsed.append({
                    "message": message,
                    "detected_topics": self._extract_topics(message),
                    "implied_audience": persona_hint,
                    "implied_outcomes": [],
                    "language_cues": self._extract_language_cues(message),
                    "tone": "unknown",
                    "awareness_hint": "solution_aware",
                    "product_context": {
                        "name": product_name,
                        "category": product_category,
                    },
                    "format_hint": format_hint,
                })

        return parsed

    def _extract_topics(self, message: str) -> List[str]:
        """Extract likely topics from message text."""
        topics = []
        message_lower = message.lower()

        # Topic keyword mapping
        topic_keywords = {
            "sugar": ["sugar", "sweetener", "sweet", "glucose"],
            "boba": ["boba", "bubble tea", "tapioca"],
            "glp-1": ["glp-1", "ozempic", "semaglutide", "mounjaro", "wegovy"],
            "bloating": ["bloat", "bloating", "gas", "digestive"],
            "protein": ["protein", "amino"],
            "energy": ["energy", "tired", "fatigue"],
            "weight": ["weight", "fat", "slim", "skinny"],
            "gut": ["gut", "microbiome", "probiotic", "digestive"],
        }

        for topic, keywords in topic_keywords.items():
            if any(kw in message_lower for kw in keywords):
                topics.append(topic)

        return topics

    def _extract_language_cues(self, message: str) -> List[str]:
        """Extract distinctive phrases and language cues."""
        cues = []

        # Look for common patterns
        patterns = [
            "tired of",
            "finally",
            "the real reason",
            "without",
            "guilt-free",
            "it's not your fault",
            "what if",
            "discover",
            "secret",
        ]

        message_lower = message.lower()
        for pattern in patterns:
            if pattern in message_lower:
                cues.append(pattern)

        return cues

    # =========================================================================
    # LAYER CLASSIFICATION
    # =========================================================================

    async def classify_message_layer(
        self,
        parsed_message: Dict[str, Any],
        product_category: str = "",
        disallowed_claims: Optional[List[str]] = None,
        llm_response: Optional[Dict] = None
    ) -> MessageClassification:
        """
        Classify a message into belief-first layers.

        Args:
            parsed_message: Parsed message dict with message text and extracted data
            product_category: Product category for context
            disallowed_claims: List of claims to flag
            llm_response: Pre-computed LLM classification

        Returns:
            MessageClassification model
        """
        message = parsed_message.get("message", "")

        if llm_response:
            return MessageClassification(
                message=message,
                primary_layer=BeliefLayer(llm_response.get("primary_layer", "OTHER")),
                secondary_layers=[
                    BeliefLayer(l) for l in llm_response.get("secondary_layers", [])
                ],
                confidence=llm_response.get("confidence", 0.5),
                detected_topics=llm_response.get("detected_topics", []),
                triggers_compliance_mode=llm_response.get("triggers_compliance_mode", False),
            )

        # Rule-based classification fallback
        return self._rule_based_classify(message, parsed_message)

    def _rule_based_classify(
        self,
        message: str,
        parsed: Dict[str, Any]
    ) -> MessageClassification:
        """
        Rule-based classification when LLM is not available.
        """
        message_lower = message.lower()

        # Check for UMP seeds
        ump_signals = ["real reason", "actually", "the truth is", "it's not",
                       "what they don't", "hidden", "secret cause"]
        if any(sig in message_lower for sig in ump_signals):
            return MessageClassification(
                message=message,
                primary_layer=BeliefLayer.UMP_SEED,
                secondary_layers=[],
                confidence=0.7,
                detected_topics=parsed.get("topics", []),
                triggers_compliance_mode=self._check_compliance_triggers(message),
            )

        # Check for proof signals
        proof_signals = ["study", "research", "proven", "clinical", "doctor",
                         "testimonial", "results", "%", "customers"]
        if any(sig in message_lower for sig in proof_signals):
            return MessageClassification(
                message=message,
                primary_layer=BeliefLayer.PROOF,
                secondary_layers=[],
                confidence=0.7,
                detected_topics=parsed.get("topics", []),
                triggers_compliance_mode=self._check_compliance_triggers(message),
            )

        # Check for benefit signals
        benefit_signals = ["feel", "get", "achieve", "experience", "enjoy",
                          "without", "finally", "never again"]
        if any(sig in message_lower for sig in benefit_signals):
            return MessageClassification(
                message=message,
                primary_layer=BeliefLayer.BENEFIT,
                secondary_layers=[],
                confidence=0.6,
                detected_topics=parsed.get("topics", []),
                triggers_compliance_mode=self._check_compliance_triggers(message),
            )

        # Default to expression
        return MessageClassification(
            message=message,
            primary_layer=BeliefLayer.EXPRESSION,
            secondary_layers=[],
            confidence=0.5,
            detected_topics=parsed.get("topics", []),
            triggers_compliance_mode=self._check_compliance_triggers(message),
        )

    def _check_compliance_triggers(self, message: str) -> bool:
        """Check if message contains compliance-sensitive content."""
        message_lower = message.lower()

        # Drug references
        drugs = ["ozempic", "wegovy", "mounjaro", "semaglutide", "tirzepatide"]
        if any(drug in message_lower for drug in drugs):
            return True

        # Medical claims
        medical = ["treat", "cure", "prevent disease", "medical", "prescription"]
        if any(term in message_lower for term in medical):
            return True

        return False

    # =========================================================================
    # CANVAS ASSEMBLY
    # =========================================================================

    async def assemble_draft_canvas(
        self,
        classifications: List[Dict[str, Any]],
        product_context: Dict[str, Any],
        format_hint: Optional[str] = None,
        persona_hint: Optional[str] = None,
        llm_response: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Assemble a draft Belief-First Master Canvas from messages and context.

        Uses LLM (Claude Opus) to intelligently analyze messages and INFER
        the belief structure, filling in gaps with reasonable hypotheses.

        Args:
            classifications: Layer classifications for each message (as dicts)
            product_context: Product truth from database (as dict)
            format_hint: ad, landing_page, video, email
            persona_hint: Persona description hint
            llm_response: Pre-computed LLM canvas assembly

        Returns:
            Dict with canvas, research_needed, proof_needed
        """
        trace_map: List[Dict] = []

        # Initialize canvas structure
        canvas = {
            "research_canvas": {
                "market_context": {},
                "persona_context": {},
                "observed_pain": {},
                "pattern_detection": {},
                "then_vs_now": {},
                "solutions_attempted": {},
                "desired_progress": {},
                "knowledge_gaps": {},
                "candidate_root_causes": [],
            },
            "belief_canvas": {
                "belief_context": {},
                "persona_filter": {"jtbd": {}, "constraints": {}, "persona_sublayers": {}},
                "unique_mechanism": {"ump": {}, "ums": {}, "reinterpreted_pain": ""},
                "progress_justification": {"benefits": {}, "features": []},
                "proof_stack": {},
                "expression": {},
            },
            "integrity_checks": [],
        }

        # Fill from product context (OBSERVED data)
        if product_context:
            self._fill_canvas_from_product_context(canvas, product_context, trace_map)

        # If we have a pre-computed LLM response, use it
        if llm_response:
            self._fill_canvas_from_llm_response(canvas, llm_response, trace_map)
        else:
            # Use LLM to intelligently infer belief structure
            llm_canvas = await self._llm_assemble_canvas(
                classifications=classifications,
                product_context=product_context,
                format_hint=format_hint,
                persona_hint=persona_hint,
            )

            if llm_canvas:
                self._fill_canvas_from_llm_response(canvas, llm_canvas, trace_map)
                trace_map.append({
                    "field_path": "belief_canvas",
                    "source": "llm_inference",
                    "source_detail": "Claude Opus analysis of messages + product context",
                    "evidence_status": EvidenceStatus.INFERRED.value,
                })
            else:
                # Fallback to rule-based if LLM fails
                self._fill_canvas_from_classifications(
                    canvas, classifications, trace_map
                )

        # Apply hints
        if format_hint:
            canvas["belief_canvas"]["expression"]["formats"] = [format_hint]
            trace_map.append({
                "field_path": "belief_canvas.expression.formats",
                "source": "user_input",
                "source_detail": f"format_hint: {format_hint}",
                "evidence_status": EvidenceStatus.OBSERVED.value,
            })

        # Identify gaps
        research_needed, proof_needed = self._identify_canvas_gaps(canvas)

        return {
            "canvas": canvas,
            "research_needed": research_needed,
            "proof_needed": proof_needed,
            "trace_map": trace_map,
        }

    async def _llm_assemble_canvas(
        self,
        classifications: List[Dict[str, Any]],
        product_context: Dict[str, Any],
        format_hint: Optional[str] = None,
        persona_hint: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Use LLM to intelligently analyze messages and infer belief structure.

        This is the core intelligence - it takes rough messages and product context
        and infers the full belief hierarchy (UMP, UMS, persona, benefits, etc.)
        """
        try:
            # Build the prompt with all context
            messages_text = "\n".join([
                f"- Message {i+1} ({c.get('primary_layer', 'unknown')}): {c.get('message', '')}"
                for i, c in enumerate(classifications)
            ])

            product_text = ""
            if product_context:
                product_text = f"""
Product Name: {product_context.get('name', 'Unknown')}
Category: {product_context.get('category', 'Unknown')}
Ingredients: {json.dumps(product_context.get('ingredients', []))}
Allowed Claims: {product_context.get('allowed_claims', [])}
Disallowed Claims: {product_context.get('disallowed_claims', [])}
"""

            prompt = f"""Analyze these marketing messages and infer the complete belief-first hierarchy.

## Messages to Analyze:
{messages_text}

## Product Context:
{product_text}

## Additional Context:
- Format hint: {format_hint or 'not specified'}
- Persona hint: {persona_hint or 'not specified'}

## Your Task:
Based on this messaging, INFER what belief structure is being used. Even if only one hook is provided,
deduce what UMP (unique mechanism problem), UMS (unique mechanism solution), persona targeting,
and benefits are IMPLIED by the messaging.

Think about:
1. What OLD BELIEF is being challenged? (UMP - what did they think was the cause?)
2. What NEW BELIEF is being offered? (UMP - what's the REAL cause?)
3. How does the product solve this? (UMS - the mechanism)
4. Who is this targeting? (Persona - JTBD, constraints)
5. What benefits are promised? (immediate, short-term, long-term)

Return a JSON object with this structure:
{{
    "belief_canvas": {{
        "belief_context": {{
            "current_awareness_state": "problem_aware|solution_aware|etc",
            "promise_boundary": "what is/isn't being claimed",
            "why_now": "any urgency or timing elements"
        }},
        "persona_filter": {{
            "jtbd": {{
                "functional": "what job they need done",
                "emotional": "how they want to feel",
                "identity": "who they want to be"
            }},
            "constraints": ["time", "money", "energy", "identity"],
            "dominant_constraint": "the main blocker addressed"
        }},
        "unique_mechanism": {{
            "ump": {{
                "old_accepted_explanation": "what they used to believe caused the problem",
                "reframed_root_cause": "what the message says is the REAL cause",
                "why_past_solutions_failed": "why other approaches didn't work",
                "externalized_blame": "how it's not their fault",
                "missing_1_percent": "the key insight they were missing"
            }},
            "ums": {{
                "macro_solution_logic": "one-sentence solution logic",
                "micro_mechanism": "how it works step by step"
            }},
            "reinterpreted_pain": "how the mechanism explains their past pain"
        }},
        "progress_justification": {{
            "benefits": {{
                "immediate": "what they get right away",
                "short_term": "what they get in days/weeks",
                "long_term": "what they get over time"
            }},
            "features": ["only if clearly stated in messages"]
        }},
        "proof_stack": {{
            "solution_efficacy": {{"present": [], "missing": []}},
            "identity_social": {{"present": [], "missing": []}}
        }},
        "expression": {{
            "core_hook": "the main hook/headline",
            "primary_angle": "the main messaging angle"
        }}
    }},
    "research_canvas": {{
        "market_context": {{
            "category": "{product_context.get('category', 'unknown')}",
            "detected_topics": ["inferred topics from messages"]
        }},
        "persona_context": {{
            "inferred_persona": "who this is targeting"
        }},
        "observed_pain": {{
            "symptoms_physical": ["inferred physical symptoms"],
            "symptoms_emotional": ["inferred emotional pain"]
        }},
        "candidate_root_causes": ["hypothesized causes from the UMP"]
    }}
}}

Be thorough - even a single hook implies an entire belief structure. Fill in what's implied."""

            # Use Claude Opus for intelligent analysis
            agent = Agent(
                model=Config.get_model("belief_canvas") or "claude-sonnet-4-20250514",
                system_prompt=DRAFT_CANVAS_SYSTEM_PROMPT
            )

            result = await agent.run(prompt)
            content = result.output

            # Parse JSON from response with robust handling
            parsed = self._parse_llm_json(content)
            if parsed:
                logger.info("LLM canvas assembly successful")
                return parsed
            else:
                logger.warning("Could not parse JSON from LLM response")
                return None

        except Exception as e:
            logger.error(f"LLM canvas assembly failed: {e}")
            return None

    def _parse_llm_json(self, content: str) -> Optional[Dict[str, Any]]:
        """
        Robustly parse JSON from LLM output.

        Handles common issues:
        - JSON embedded in markdown code blocks
        - Trailing commas
        - Single quotes instead of double quotes
        - Comments in JSON
        - Extra text before/after JSON
        """
        if not content:
            return None

        # Try to extract JSON from markdown code blocks first
        code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
        if code_block_match:
            json_str = code_block_match.group(1).strip()
        else:
            # Find the outermost JSON object
            # Use a more careful approach - find matching braces
            json_str = self._extract_json_object(content)

        if not json_str:
            logger.warning("No JSON found in LLM response")
            return None

        # Try parsing as-is first
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.debug(f"Initial JSON parse failed: {e}")

        # Try common repairs
        repaired = json_str

        # Remove trailing commas before } or ]
        repaired = re.sub(r',(\s*[}\]])', r'\1', repaired)

        # Remove JavaScript-style comments
        repaired = re.sub(r'//.*?$', '', repaired, flags=re.MULTILINE)
        repaired = re.sub(r'/\*[\s\S]*?\*/', '', repaired)

        # Try parsing repaired JSON
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON repair failed: {e}")
            logger.debug(f"Problematic JSON (first 500 chars): {repaired[:500]}")
            return None

    def _extract_json_object(self, content: str) -> Optional[str]:
        """
        Extract the outermost JSON object from content by matching braces.
        More reliable than greedy regex for nested structures.
        """
        start_idx = content.find('{')
        if start_idx == -1:
            return None

        brace_count = 0
        in_string = False
        escape_next = False
        end_idx = start_idx

        for i, char in enumerate(content[start_idx:], start_idx):
            if escape_next:
                escape_next = False
                continue

            if char == '\\' and in_string:
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i
                    break

        if brace_count != 0:
            # Unbalanced braces - try the greedy regex as fallback
            json_match = re.search(r'\{[\s\S]*\}', content)
            return json_match.group() if json_match else None

        return content[start_idx:end_idx + 1]

    def _fill_canvas_from_product_context(
        self,
        canvas: Dict[str, Any],
        product_context: Dict[str, Any],
        trace_map: List[Dict],
    ) -> None:
        """Fill canvas with OBSERVED data from product context dict."""
        bc = canvas["belief_canvas"]
        rc = canvas["research_canvas"]

        # Promise boundary
        if product_context.get("promise_boundary_default"):
            bc["belief_context"]["promise_boundary"] = product_context["promise_boundary_default"]
            trace_map.append({
                "field_path": "belief_canvas.belief_context.promise_boundary",
                "source": "product_db",
                "source_detail": "products.promise_boundary",
                "evidence_status": EvidenceStatus.OBSERVED.value,
            })

        # Pre-built mechanisms
        mechanisms = product_context.get("mechanisms", [])
        for mech in mechanisms:
            if mech.get("type") == "ump" and mech.get("root_cause"):
                bc["unique_mechanism"]["ump"]["reframed_root_cause"] = mech.get("root_cause")
                trace_map.append({
                    "field_path": "belief_canvas.unique_mechanism.ump.reframed_root_cause",
                    "source": "product_db",
                    "source_detail": f"mechanism: {mech.get('name')}",
                    "evidence_status": EvidenceStatus.OBSERVED.value,
                })

        # Market context from category
        if product_context.get("category"):
            rc["market_context"]["category"] = product_context["category"]
            trace_map.append({
                "field_path": "research_canvas.market_context.category",
                "source": "product_db",
                "source_detail": "products.category",
                "evidence_status": EvidenceStatus.OBSERVED.value,
            })

    def _fill_canvas_from_classifications(
        self,
        canvas: Dict[str, Any],
        classifications: List[Dict[str, Any]],
        trace_map: List[Dict],
    ) -> None:
        """Fill canvas with INFERRED data from message classifications."""
        bc = canvas["belief_canvas"]
        rc = canvas["research_canvas"]

        for i, classification in enumerate(classifications):
            msg = classification.get("message", "")
            msg_ref = f"message[{i}]"
            # Handle both enum value (lowercase) and enum name (uppercase)
            primary_layer = classification.get("primary_layer", "other")
            if isinstance(primary_layer, str):
                primary_layer = primary_layer.lower()

            # UMP seeds
            if primary_layer == "ump_seed":
                if not bc["unique_mechanism"]["ump"].get("reframed_root_cause"):
                    bc["unique_mechanism"]["ump"]["reframed_root_cause"] = msg
                    trace_map.append({
                        "field_path": "belief_canvas.unique_mechanism.ump.reframed_root_cause",
                        "source": "message",
                        "source_detail": msg_ref,
                        "evidence_status": EvidenceStatus.INFERRED.value,
                    })

            # Benefits
            elif primary_layer == "benefit":
                if not bc["progress_justification"]["benefits"].get("immediate"):
                    bc["progress_justification"]["benefits"]["immediate"] = msg
                    trace_map.append({
                        "field_path": "belief_canvas.progress_justification.benefits.immediate",
                        "source": "message",
                        "source_detail": msg_ref,
                        "evidence_status": EvidenceStatus.INFERRED.value,
                    })

            # Expression/Hook
            elif primary_layer == "expression":
                if not bc["expression"].get("core_hook"):
                    bc["expression"]["core_hook"] = msg
                    trace_map.append({
                        "field_path": "belief_canvas.expression.core_hook",
                        "source": "message",
                        "source_detail": msg_ref,
                        "evidence_status": EvidenceStatus.INFERRED.value,
                    })

            # Proof
            elif primary_layer == "proof":
                if not bc["proof_stack"].get("testimonials"):
                    bc["proof_stack"]["testimonials"] = [msg]
                    trace_map.append({
                        "field_path": "belief_canvas.proof_stack.testimonials",
                        "source": "message",
                        "source_detail": msg_ref,
                        "evidence_status": EvidenceStatus.INFERRED.value,
                    })

            # Persona filter
            elif primary_layer == "persona_filter":
                if not bc["persona_filter"].get("target_description"):
                    bc["persona_filter"]["target_description"] = msg
                    trace_map.append({
                        "field_path": "belief_canvas.persona_filter.target_description",
                        "source": "message",
                        "source_detail": msg_ref,
                        "evidence_status": EvidenceStatus.INFERRED.value,
                    })

            # UMS seeds
            elif primary_layer == "ums_seed":
                if not bc["unique_mechanism"]["ums"].get("mechanism"):
                    bc["unique_mechanism"]["ums"]["mechanism"] = msg
                    trace_map.append({
                        "field_path": "belief_canvas.unique_mechanism.ums.mechanism",
                        "source": "message",
                        "source_detail": msg_ref,
                        "evidence_status": EvidenceStatus.INFERRED.value,
                    })

            # Collect topics
            topics = classification.get("detected_topics", [])
            for topic in topics:
                if "detected_topics" not in rc["market_context"]:
                    rc["market_context"]["detected_topics"] = []
                if topic not in rc["market_context"]["detected_topics"]:
                    rc["market_context"]["detected_topics"].append(topic)

    def _fill_canvas_from_llm_response(
        self,
        canvas: Dict[str, Any],
        llm_response: Dict,
        trace_map: List[Dict],
    ) -> None:
        """Fill canvas from pre-computed LLM response."""
        if "belief_canvas" in llm_response:
            bc = llm_response["belief_canvas"]

            # Merge belief context
            if "belief_context" in bc:
                for key, value in bc["belief_context"].items():
                    if value:
                        canvas["belief_canvas"]["belief_context"][key] = value
                        trace_map.append({
                            "field_path": f"belief_canvas.belief_context.{key}",
                            "source": "llm_inference",
                            "source_detail": "DraftCanvasAssemblerNode",
                            "evidence_status": EvidenceStatus.INFERRED.value,
                        })

            # Merge unique mechanism
            if "unique_mechanism" in bc:
                for section in ["ump", "ums", "reinterpreted_pain"]:
                    if section in bc["unique_mechanism"]:
                        section_data = bc["unique_mechanism"][section]
                        if isinstance(section_data, dict):
                            for key, value in section_data.items():
                                if value:
                                    canvas["belief_canvas"]["unique_mechanism"][section][key] = value

    def _identify_canvas_gaps(
        self,
        canvas: Dict[str, Any]
    ) -> Tuple[List[Dict], List[Dict]]:
        """Identify gaps in the canvas that need research or proof."""
        research_needed = []
        proof_needed = []

        bc = canvas.get("belief_canvas", {})

        # Check UMP completeness
        ump = bc.get("unique_mechanism", {}).get("ump", {})
        if not ump.get("reframed_root_cause"):
            research_needed.append({
                "field": "ump.reframed_root_cause",
                "question": "What is the reframed root cause of the problem?",
                "priority": "critical",
            })

        if not ump.get("why_past_solutions_failed"):
            research_needed.append({
                "field": "ump.why_past_solutions_failed",
                "question": "Why have past solutions failed for this audience?",
                "priority": "important",
            })

        # Check proof stack
        proof_stack = bc.get("proof_stack", {})
        if not proof_stack.get("solution_efficacy", {}).get("present"):
            proof_needed.append({
                "proof_type": "solution_efficacy",
                "why_needed": "No solution efficacy proof present",
                "priority": "important",
            })

        return research_needed, proof_needed

    def _fill_from_product_context(
        self,
        canvas: BeliefFirstMasterCanvas,
        product_context: ProductContext,
        trace_map: List[TraceItem],
    ) -> None:
        """Fill canvas with OBSERVED data from product context."""

        # Promise boundary
        if product_context.promise_boundary_default:
            canvas.belief_canvas.belief_context["promise_boundary"] = \
                product_context.promise_boundary_default
            trace_map.append(TraceItem(
                field_path="belief_canvas.belief_context.promise_boundary",
                source="product_db",
                source_detail="products.promise_boundary",
                evidence_status=EvidenceStatus.OBSERVED,
            ))

        # Pre-built mechanisms
        if product_context.mechanisms:
            for mech in product_context.mechanisms:
                if mech.get("type") == "ump" and mech.get("root_cause"):
                    canvas.belief_canvas.unique_mechanism["ump"]["reframed_root_cause"] = \
                        mech.get("root_cause")
                    trace_map.append(TraceItem(
                        field_path="belief_canvas.unique_mechanism.ump.reframed_root_cause",
                        source="product_db",
                        source_detail=f"mechanism: {mech.get('name')}",
                        evidence_status=EvidenceStatus.OBSERVED,
                    ))

        # Market context from category
        canvas.research_canvas.market_context["category"] = product_context.category
        trace_map.append(TraceItem(
            field_path="research_canvas.market_context.category",
            source="product_db",
            source_detail="products.category",
            evidence_status=EvidenceStatus.OBSERVED,
        ))

    def _fill_from_messages(
        self,
        canvas: BeliefFirstMasterCanvas,
        messages: List[str],
        classifications: List[MessageClassification],
        trace_map: List[TraceItem],
    ) -> None:
        """Fill canvas with INFERRED data from message analysis."""

        for i, (msg, classification) in enumerate(zip(messages, classifications)):
            msg_ref = f"message[{i}]"

            # UMP seeds
            if classification.primary_layer == BeliefLayer.UMP_SEED:
                if not canvas.belief_canvas.unique_mechanism["ump"]["reframed_root_cause"]:
                    canvas.belief_canvas.unique_mechanism["ump"]["reframed_root_cause"] = msg
                    trace_map.append(TraceItem(
                        field_path="belief_canvas.unique_mechanism.ump.reframed_root_cause",
                        source="message",
                        source_detail=msg_ref,
                        evidence_status=EvidenceStatus.INFERRED,
                    ))

            # Benefits
            elif classification.primary_layer == BeliefLayer.BENEFIT:
                benefits = canvas.belief_canvas.progress_justification["benefits"]
                if not benefits["immediate"]:
                    benefits["immediate"] = msg
                    trace_map.append(TraceItem(
                        field_path="belief_canvas.progress_justification.benefits.immediate",
                        source="message",
                        source_detail=msg_ref,
                        evidence_status=EvidenceStatus.INFERRED,
                    ))

            # Expression/Hook
            elif classification.primary_layer == BeliefLayer.EXPRESSION:
                if not canvas.belief_canvas.expression["core_hook"]:
                    canvas.belief_canvas.expression["core_hook"] = msg
                    trace_map.append(TraceItem(
                        field_path="belief_canvas.expression.core_hook",
                        source="message",
                        source_detail=msg_ref,
                        evidence_status=EvidenceStatus.INFERRED,
                    ))

            # Topics for context
            for topic in classification.detected_topics:
                if topic not in (canvas.research_canvas.market_context.get("detected_topics") or []):
                    if "detected_topics" not in canvas.research_canvas.market_context:
                        canvas.research_canvas.market_context["detected_topics"] = []
                    canvas.research_canvas.market_context["detected_topics"].append(topic)

    def _fill_from_llm_response(
        self,
        canvas: BeliefFirstMasterCanvas,
        llm_response: Dict,
        trace_map: List[TraceItem],
    ) -> None:
        """Fill canvas from pre-computed LLM response."""
        if "belief_canvas" in llm_response:
            bc = llm_response["belief_canvas"]

            # Merge belief context
            if "belief_context" in bc:
                for key, value in bc["belief_context"].items():
                    if value:
                        canvas.belief_canvas.belief_context[key] = value
                        trace_map.append(TraceItem(
                            field_path=f"belief_canvas.belief_context.{key}",
                            source="llm_inference",
                            source_detail="DraftCanvasAssemblerNode",
                            evidence_status=EvidenceStatus.INFERRED,
                        ))

            # Merge unique mechanism
            if "unique_mechanism" in bc:
                for section in ["ump", "ums", "reinterpreted_pain"]:
                    if section in bc["unique_mechanism"]:
                        for key, value in bc["unique_mechanism"][section].items():
                            if value:
                                canvas.belief_canvas.unique_mechanism[section][key] = value

    def _identify_gaps(
        self,
        canvas: BeliefFirstMasterCanvas
    ) -> Tuple[List[Dict], List[Dict]]:
        """Identify gaps in the canvas that need research or proof."""
        research_needed = []
        proof_needed = []

        bc = canvas.belief_canvas

        # Check UMP completeness
        ump = bc.unique_mechanism.get("ump", {})
        if not ump.get("reframed_root_cause"):
            research_needed.append({
                "field": "ump.reframed_root_cause",
                "question": "What is the reframed root cause of the problem?",
                "priority": "critical",
            })

        if not ump.get("why_past_solutions_failed"):
            research_needed.append({
                "field": "ump.why_past_solutions_failed",
                "question": "Why have past solutions failed for this audience?",
                "priority": "important",
            })

        # Check proof stack
        proof_stack = bc.proof_stack
        if not proof_stack.get("solution_efficacy", {}).get("present"):
            proof_needed.append({
                "proof_type": "solution_efficacy",
                "why_needed": "No solution efficacy proof present",
                "priority": "important",
            })

        return research_needed, proof_needed

    # =========================================================================
    # INTEGRITY CHECKS
    # =========================================================================

    def run_integrity_checks(
        self,
        canvas: BeliefFirstMasterCanvas,
        is_draft_mode: bool = True,
    ) -> List[IntegrityCheckResult]:
        """
        Run integrity validation on the canvas.

        Checks:
        1. Research precedes framing (warning in draft mode)
        2. UMP explains failure before success
        3. Features appear only after benefits
        4. Proof reinforces belief, never introduces
        5. Constraints are respected
        """
        results = []

        # Check 1: Research precedes framing
        research_empty = self._is_research_canvas_empty(canvas.research_canvas)
        if research_empty and not is_draft_mode:
            results.append(IntegrityCheckResult(
                check_name="research_precedes_framing",
                passed=False,
                notes="Research canvas is empty but research_mode was expected",
                severity="error",
            ))
        elif research_empty:
            results.append(IntegrityCheckResult(
                check_name="research_precedes_framing",
                passed=True,
                notes="Draft mode - research not required but recommended",
                severity="warning",
            ))
        else:
            results.append(IntegrityCheckResult(
                check_name="research_precedes_framing",
                passed=True,
                notes="Research canvas populated",
            ))

        # Check 2: UMP explains failure before success
        ump = canvas.belief_canvas.unique_mechanism.get("ump", {})
        ums = canvas.belief_canvas.unique_mechanism.get("ums", {})

        if ums.get("macro_solution_logic") and not ump.get("why_past_solutions_failed"):
            results.append(IntegrityCheckResult(
                check_name="ump_explains_failure_first",
                passed=False,
                notes="UMS present but UMP doesn't explain why past solutions failed",
                severity="error",
            ))
        else:
            results.append(IntegrityCheckResult(
                check_name="ump_explains_failure_first",
                passed=True,
                notes="UMP properly precedes UMS",
            ))

        # Check 3: Features after benefits
        benefits = canvas.belief_canvas.progress_justification.get("benefits", {})
        features = canvas.belief_canvas.progress_justification.get("features", [])

        has_benefits = any([
            benefits.get("immediate"),
            benefits.get("short_term"),
            benefits.get("long_term"),
        ])

        if features and not has_benefits:
            results.append(IntegrityCheckResult(
                check_name="features_after_benefits",
                passed=False,
                notes="Features listed but no benefits established",
                severity="warning",
            ))
        else:
            results.append(IntegrityCheckResult(
                check_name="features_after_benefits",
                passed=True,
                notes="Benefits precede features (or no features listed)",
            ))

        # Check 4: Proof reinforces, doesn't introduce
        # This would require deeper analysis - simplified for now
        results.append(IntegrityCheckResult(
            check_name="proof_reinforces_belief",
            passed=True,
            notes="Manual review recommended for proof ordering",
        ))

        return results

    def _is_research_canvas_empty(self, research: ResearchCanvas) -> bool:
        """Check if research canvas has any populated fields."""
        # Check if any lists have content
        if research.observed_pain.get("symptoms_physical"):
            return False
        if research.pattern_detection.get("triggers"):
            return False
        if research.solutions_attempted.get("worked_briefly"):
            return False
        if research.candidate_root_causes:
            return False

        return True

    # =========================================================================
    # RISK DETECTION
    # =========================================================================

    def detect_risks(
        self,
        canvas: BeliefFirstMasterCanvas,
        product_context: Optional[ProductContext],
        llm_response: Optional[List[Dict]] = None,
    ) -> List[RiskFlag]:
        """
        Detect compliance and messaging risks in the canvas.

        Args:
            canvas: The assembled canvas
            product_context: Product context with disallowed claims
            llm_response: Pre-computed LLM risk analysis

        Returns:
            List of RiskFlag objects
        """
        risks = []

        if llm_response:
            for risk_dict in llm_response:
                risks.append(RiskFlag(
                    type=RiskFlagType(risk_dict.get("type", "AMBIGUITY")),
                    severity=RiskSeverity(risk_dict.get("severity", "medium")),
                    reason=risk_dict.get("reason", ""),
                    suggested_fix=risk_dict.get("suggested_fix", ""),
                    affected_fields=risk_dict.get("affected_fields", []),
                ))
            return risks

        # Rule-based risk detection
        risks.extend(self._detect_medical_claims(canvas))
        risks.extend(self._detect_drug_references(canvas))

        if product_context:
            risks.extend(self._detect_disallowed_claims(canvas, product_context))

        return risks

    def _detect_medical_claims(self, canvas: BeliefFirstMasterCanvas) -> List[RiskFlag]:
        """Detect potential medical claims."""
        risks = []
        medical_terms = ["treat", "cure", "prevent", "heal", "remedy", "therapy"]

        # Check UMP/UMS
        ump = canvas.belief_canvas.unique_mechanism.get("ump", {})
        for field, value in ump.items():
            if value and isinstance(value, str):
                value_lower = value.lower()
                for term in medical_terms:
                    if term in value_lower:
                        risks.append(RiskFlag(
                            type=RiskFlagType.MEDICAL_CLAIM,
                            severity=RiskSeverity.HIGH,
                            reason=f"Potential medical claim: '{term}' found in UMP",
                            suggested_fix=f"Reframe without '{term}' - focus on comfort/support",
                            affected_fields=[f"belief_canvas.unique_mechanism.ump.{field}"],
                        ))

        return risks

    def _detect_drug_references(self, canvas: BeliefFirstMasterCanvas) -> List[RiskFlag]:
        """Detect drug name references that need careful handling."""
        risks = []
        drug_names = ["ozempic", "wegovy", "mounjaro", "semaglutide", "tirzepatide"]

        # Scan entire canvas for drug names
        canvas_str = json.dumps(canvas.belief_canvas.model_dump()).lower()

        for drug in drug_names:
            if drug in canvas_str:
                risks.append(RiskFlag(
                    type=RiskFlagType.DRUG_REFERENCE,
                    severity=RiskSeverity.MEDIUM,
                    reason=f"Drug reference found: {drug}",
                    suggested_fix="Use 'GLP-1 medications' instead of specific drug names",
                    affected_fields=["canvas_wide"],
                ))

        return risks

    def _detect_disallowed_claims(
        self,
        canvas: BeliefFirstMasterCanvas,
        product_context: ProductContext
    ) -> List[RiskFlag]:
        """Check for disallowed claims from product context."""
        risks = []

        if not product_context.disallowed_claims:
            return risks

        canvas_str = json.dumps(canvas.belief_canvas.model_dump()).lower()

        for claim in product_context.disallowed_claims:
            if claim.lower() in canvas_str:
                risks.append(RiskFlag(
                    type=RiskFlagType.PROMISE_BOUNDARY,
                    severity=RiskSeverity.HIGH,
                    reason=f"Disallowed claim found: {claim}",
                    suggested_fix=f"Remove or reframe: {claim}",
                    affected_fields=["canvas_wide"],
                ))

        return risks

    # =========================================================================
    # DICT-BASED METHODS FOR PIPELINE
    # =========================================================================

    async def detect_risks(
        self,
        canvas: Dict[str, Any],
        product_context: Dict[str, Any],
        message_classifications: Optional[List[Dict]] = None,
    ) -> List[RiskFlag]:
        """
        Detect compliance and messaging risks in the canvas (dict-based).

        Args:
            canvas: The assembled canvas dict
            product_context: Product context dict with disallowed claims
            message_classifications: Message classifications for context

        Returns:
            List of RiskFlag objects
        """
        risks = []

        # Rule-based risk detection on dict
        risks.extend(self._detect_medical_claims_dict(canvas))
        risks.extend(self._detect_drug_references_dict(canvas))

        if product_context:
            disallowed = product_context.get("disallowed_claims", [])
            if disallowed:
                risks.extend(self._detect_disallowed_claims_dict(canvas, disallowed))

        return risks

    def _detect_medical_claims_dict(self, canvas: Dict[str, Any]) -> List[RiskFlag]:
        """Detect potential medical claims (dict-based)."""
        risks = []
        medical_terms = ["treat", "cure", "prevent", "heal", "remedy", "therapy"]

        bc = canvas.get("belief_canvas", {})
        ump = bc.get("unique_mechanism", {}).get("ump", {})

        for field, value in ump.items():
            if value and isinstance(value, str):
                value_lower = value.lower()
                for term in medical_terms:
                    if term in value_lower:
                        risks.append(RiskFlag(
                            type=RiskFlagType.MEDICAL_CLAIM,
                            severity=RiskSeverity.HIGH,
                            reason=f"Potential medical claim: '{term}' found in UMP",
                            suggested_fix=f"Reframe without '{term}' - focus on comfort/support",
                            affected_fields=[f"belief_canvas.unique_mechanism.ump.{field}"],
                        ))

        return risks

    def _detect_drug_references_dict(self, canvas: Dict[str, Any]) -> List[RiskFlag]:
        """Detect drug name references (dict-based)."""
        risks = []
        drug_names = ["ozempic", "wegovy", "mounjaro", "semaglutide", "tirzepatide"]

        canvas_str = json.dumps(canvas.get("belief_canvas", {})).lower()

        for drug in drug_names:
            if drug in canvas_str:
                risks.append(RiskFlag(
                    type=RiskFlagType.DRUG_REFERENCE,
                    severity=RiskSeverity.MEDIUM,
                    reason=f"Drug reference found: {drug}",
                    suggested_fix="Use 'GLP-1 medications' instead of specific drug names",
                    affected_fields=["canvas_wide"],
                ))

        return risks

    def _detect_disallowed_claims_dict(
        self,
        canvas: Dict[str, Any],
        disallowed_claims: List[str]
    ) -> List[RiskFlag]:
        """Check for disallowed claims (dict-based)."""
        risks = []

        canvas_str = json.dumps(canvas.get("belief_canvas", {})).lower()

        for claim in disallowed_claims:
            if claim.lower() in canvas_str:
                risks.append(RiskFlag(
                    type=RiskFlagType.PROMISE_BOUNDARY,
                    severity=RiskSeverity.HIGH,
                    reason=f"Disallowed claim found: {claim}",
                    suggested_fix=f"Remove or reframe: {claim}",
                    affected_fields=["canvas_wide"],
                ))

        return risks

    def run_integrity_checks(
        self,
        canvas: Dict[str, Any],
        draft_mode: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Run integrity validation on the canvas (dict-based).

        Checks:
        1. Research precedes framing (warning in draft mode)
        2. UMP explains failure before success
        3. Features appear only after benefits
        4. Proof reinforces belief, never introduces
        5. Constraints are respected

        Returns:
            List of check results as dicts
        """
        results = []

        rc = canvas.get("research_canvas", {})
        bc = canvas.get("belief_canvas", {})

        # Check 1: Research precedes framing
        research_empty = self._is_research_canvas_empty_dict(rc)
        if research_empty and not draft_mode:
            results.append({
                "check": "research_precedes_framing",
                "passed": False,
                "notes": "Research canvas is empty but research_mode was expected",
                "severity": "error",
            })
        elif research_empty:
            results.append({
                "check": "research_precedes_framing",
                "passed": True,
                "notes": "Draft mode - research not required but recommended",
                "severity": "warning",
            })
        else:
            results.append({
                "check": "research_precedes_framing",
                "passed": True,
                "notes": "Research canvas populated",
            })

        # Check 2: UMP explains failure before success
        ump = bc.get("unique_mechanism", {}).get("ump", {})
        ums = bc.get("unique_mechanism", {}).get("ums", {})

        if ums.get("macro_solution_logic") and not ump.get("why_past_solutions_failed"):
            results.append({
                "check": "ump_explains_failure_first",
                "passed": False,
                "notes": "UMS present but UMP doesn't explain why past solutions failed",
                "severity": "error",
            })
        else:
            results.append({
                "check": "ump_explains_failure_first",
                "passed": True,
                "notes": "UMP properly precedes UMS",
            })

        # Check 3: Features after benefits
        benefits = bc.get("progress_justification", {}).get("benefits", {})
        features = bc.get("progress_justification", {}).get("features", [])

        has_benefits = any([
            benefits.get("immediate"),
            benefits.get("short_term"),
            benefits.get("long_term"),
        ])

        if features and not has_benefits:
            results.append({
                "check": "features_after_benefits",
                "passed": False,
                "notes": "Features listed but no benefits established",
                "severity": "warning",
            })
        else:
            results.append({
                "check": "features_after_benefits",
                "passed": True,
                "notes": "Benefits precede features (or no features listed)",
            })

        # Check 4: Proof reinforces, doesn't introduce
        results.append({
            "check": "proof_reinforces_belief",
            "passed": True,
            "notes": "Manual review recommended for proof ordering",
        })

        return results

    def _is_research_canvas_empty_dict(self, research: Dict[str, Any]) -> bool:
        """Check if research canvas dict has any populated fields."""
        if research.get("observed_pain", {}).get("symptoms_physical"):
            return False
        if research.get("pattern_detection", {}).get("triggers"):
            return False
        if research.get("solutions_attempted", {}).get("worked_briefly"):
            return False
        if research.get("candidate_root_causes"):
            return False
        return True

    def render_markdown_canvas(
        self,
        canvas: Dict[str, Any],
        product_name: str = "Unknown Product",
        include_research: bool = True,
    ) -> str:
        """
        Render the canvas dict to markdown matching the user's template format.

        Args:
            canvas: The complete canvas dict
            product_name: Product name for header
            include_research: Whether to include sections 1-9

        Returns:
            Formatted markdown string
        """
        lines = []
        lines.append(f"# Belief-First Master Canvas: {product_name}")
        lines.append("")
        lines.append(f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_")
        lines.append("")

        rc = canvas.get("research_canvas", {})
        bc = canvas.get("belief_canvas", {})

        if include_research:
            lines.extend(self._render_research_canvas_dict(rc))

        lines.extend(self._render_belief_canvas_dict(bc))

        integrity = canvas.get("integrity_checks", [])
        if integrity:
            lines.extend(self._render_integrity_checks_dict(integrity))

        return "\n".join(lines)

    def _render_research_canvas_dict(self, research: Dict[str, Any]) -> List[str]:
        """Render sections 1-9 from dict."""
        lines = []
        lines.append("## I. RESEARCH / DISCOVERY CANVAS")
        lines.append("")

        # Section 1-2: Market & Persona Context
        lines.append("### 1-2. Market & Persona Context")
        mc = research.get("market_context", {})
        lines.append(f"- **Category:** {mc.get('category') or '_not specified_'}")
        lines.append(f"- **Detected Topics:** {', '.join(mc.get('detected_topics', [])) or '_none_'}")
        lines.append("")

        # Section 3: Observed Pain
        lines.append("### 3. Observed Pain & Friction")
        op = research.get("observed_pain", {})
        if op.get("symptoms_physical"):
            lines.append(f"- **Physical:** {', '.join(op['symptoms_physical'])}")
        if op.get("symptoms_emotional"):
            lines.append(f"- **Emotional:** {', '.join(op['symptoms_emotional'])}")
        if op.get("stated_problems"):
            lines.append(f"- **Stated Problems:** {', '.join(op['stated_problems'])}")
        if not op:
            lines.append("_No observed pain data yet_")
        lines.append("")

        # Section 4: Pattern Detection
        lines.append("### 4. Pattern Detection")
        pd = research.get("pattern_detection", {})
        if pd.get("triggers"):
            lines.append(f"- **Triggers:** {', '.join(pd['triggers'])}")
        if pd.get("what_reliably_fails"):
            lines.append(f"- **What Fails:** {', '.join(pd['what_reliably_fails'])}")
        if not pd:
            lines.append("_No patterns detected yet_")
        lines.append("")

        # Section 5-9: Abbreviated
        lines.append("### 5-9. Historical, Solutions, Progress, Gaps, Root Causes")
        sa = research.get("solutions_attempted", {})
        if sa:
            if sa.get("worked_briefly"):
                lines.append(f"- **Worked Briefly:** {', '.join(sa['worked_briefly'])}")
            if sa.get("never_worked"):
                lines.append(f"- **Never Worked:** {', '.join(sa['never_worked'])}")
        else:
            lines.append("_See full canvas for details_")
        lines.append("")

        return lines

    def _render_belief_canvas_dict(self, belief: Dict[str, Any]) -> List[str]:
        """Render sections 10-15 from dict."""
        lines = []
        lines.append("## II. BELIEF / MESSAGING CANVAS")
        lines.append("")

        # Section 10: Belief Context
        lines.append("### 10. Belief Context")
        bc = belief.get("belief_context", {})
        lines.append(f"- **Awareness State:** {bc.get('current_awareness_state') or '_not specified_'}")
        lines.append(f"- **Promise Boundary:** {bc.get('promise_boundary') or '_not set_'}")
        lines.append("")

        # Section 11: Persona Filter
        lines.append("### 11. Persona Filter")
        pf = belief.get("persona_filter", {})
        jtbd = pf.get("jtbd", {})
        lines.append("**JTBD:**")
        lines.append(f"- Functional: {jtbd.get('functional') or '_not specified_'}")
        lines.append(f"- Emotional: {jtbd.get('emotional') or '_not specified_'}")
        lines.append(f"- Identity: {jtbd.get('identity') or '_not specified_'}")
        lines.append("")

        constraints = pf.get("constraints", {})
        active = [k for k, v in constraints.items() if v]
        lines.append(f"**Constraints:** {', '.join(active) if active else '_none detected_'}")
        lines.append(f"**Dominant:** {pf.get('dominant_constraint') or '_not specified_'}")
        lines.append("")

        # Section 12: Unique Mechanism
        lines.append("### 12. Unique Mechanism")
        um = belief.get("unique_mechanism", {})
        ump = um.get("ump", {})
        lines.append("**UMP (Unique Mechanism Problem):**")
        lines.append(f"- Old Explanation: {ump.get('old_accepted_explanation') or '_not specified_'}")
        lines.append(f"- Reframed Root Cause: {ump.get('reframed_root_cause') or '_not specified_'}")
        lines.append(f"- Why Past Failed: {ump.get('why_past_solutions_failed') or '_not specified_'}")
        lines.append(f"- Externalized Blame: {ump.get('externalized_blame') or '_not specified_'}")
        lines.append(f"- Missing 1%: {ump.get('missing_1_percent') or '_not specified_'}")
        lines.append("")

        ums = um.get("ums", {})
        lines.append("**UMS (Unique Mechanism Solution):**")
        lines.append(f"- Macro Logic: {ums.get('macro_solution_logic') or '_not specified_'}")
        lines.append(f"- Micro Mechanism: {ums.get('micro_mechanism') or '_not specified_'}")
        lines.append("")

        # Section 13: Progress & Justification
        lines.append("### 13. Progress & Justification")
        pj = belief.get("progress_justification", {})
        benefits = pj.get("benefits", {})
        lines.append("**Benefits:**")
        lines.append(f"- Immediate: {benefits.get('immediate') or '_not specified_'}")
        lines.append(f"- Short-term: {benefits.get('short_term') or '_not specified_'}")
        lines.append(f"- Long-term: {benefits.get('long_term') or '_not specified_'}")
        lines.append("")

        # Section 14-15: Proof & Expression
        lines.append("### 14-15. Proof Stack & Expression")
        expr = belief.get("expression", {})
        lines.append(f"- **Core Hook:** {expr.get('core_hook') or '_not specified_'}")
        lines.append(f"- **Primary Angle:** {expr.get('primary_angle') or '_not specified_'}")
        lines.append(f"- **Formats:** {', '.join(expr.get('formats', [])) or '_not specified_'}")
        lines.append("")

        return lines

    def _render_integrity_checks_dict(
        self,
        checks: List[Dict[str, Any]]
    ) -> List[str]:
        """Render integrity check results from dict."""
        lines = []
        lines.append("## Integrity Checks")
        lines.append("")

        for check in checks:
            passed = check.get("passed", True)
            status = "PASS" if passed else "FAIL"
            icon = "[x]" if passed else "[ ]"
            lines.append(f"- {icon} **{check.get('check', 'Unknown')}**: {status}")
            if check.get("notes"):
                lines.append(f"  - {check['notes']}")

        lines.append("")
        return lines

    # =========================================================================
    # LEGACY PYDANTIC MODEL METHODS (kept for backwards compatibility)
    # =========================================================================

    def render_markdown_canvas_legacy(
        self,
        canvas: BeliefFirstMasterCanvas,
        include_research: bool = True,
    ) -> str:
        """
        Render the canvas to markdown matching the user's template format.

        Args:
            canvas: The complete canvas
            include_research: Whether to include sections 1-9

        Returns:
            Formatted markdown string
        """
        lines = []
        lines.append("# Belief-First Master Canvas")
        lines.append("")

        if include_research:
            lines.extend(self._render_research_canvas(canvas.research_canvas))

        lines.extend(self._render_belief_canvas(canvas.belief_canvas))
        lines.extend(self._render_integrity_checks(canvas.integrity_checks))

        return "\n".join(lines)

    def _render_research_canvas(self, research: ResearchCanvas) -> List[str]:
        """Render sections 1-9."""
        lines = []
        lines.append("## I. RESEARCH / DISCOVERY CANVAS")
        lines.append("")

        # Section 1-2: Market & Persona Context
        lines.append("### 1-2. Market & Persona Context")
        mc = research.market_context
        lines.append(f"- **Category:** {mc.get('category') or '_not specified_'}")
        lines.append(f"- **Market Sophistication:** {mc.get('market_sophistication') or '_not assessed_'}")
        lines.append("")

        # Section 3: Observed Pain
        lines.append("### 3. Observed Pain & Friction")
        op = research.observed_pain
        if op.get("symptoms_physical"):
            lines.append(f"- **Physical:** {', '.join(op['symptoms_physical'])}")
        if op.get("symptoms_emotional"):
            lines.append(f"- **Emotional:** {', '.join(op['symptoms_emotional'])}")
        if op.get("stated_problems"):
            lines.append(f"- **Stated Problems:** {', '.join(op['stated_problems'])}")
        lines.append("")

        # Section 4: Pattern Detection
        lines.append("### 4. Pattern Detection")
        pd = research.pattern_detection
        if pd.get("triggers"):
            lines.append(f"- **Triggers:** {', '.join(pd['triggers'])}")
        if pd.get("what_reliably_fails"):
            lines.append(f"- **What Fails:** {', '.join(pd['what_reliably_fails'])}")
        lines.append("")

        # Section 5-9: Abbreviated
        lines.append("### 5-9. Historical, Solutions, Progress, Gaps, Root Causes")
        lines.append("_See full canvas for details_")
        lines.append("")

        return lines

    def _render_belief_canvas(self, belief: BeliefCanvas) -> List[str]:
        """Render sections 10-15."""
        lines = []
        lines.append("## II. BELIEF / MESSAGING CANVAS")
        lines.append("")

        # Section 10: Belief Context
        lines.append("### 10. Belief Context")
        bc = belief.belief_context
        lines.append(f"- **Awareness State:** {bc.get('current_awareness_state') or '_not specified_'}")
        lines.append(f"- **Promise Boundary:** {bc.get('promise_boundary') or '_not set_'}")
        lines.append("")

        # Section 11: Persona Filter
        lines.append("### 11. Persona Filter")
        pf = belief.persona_filter
        jtbd = pf.get("jtbd", {})
        lines.append("**JTBD:**")
        lines.append(f"- Functional: {jtbd.get('functional') or '_not specified_'}")
        lines.append(f"- Emotional: {jtbd.get('emotional') or '_not specified_'}")
        lines.append(f"- Identity: {jtbd.get('identity') or '_not specified_'}")
        lines.append("")

        constraints = pf.get("constraints", {})
        active = [k for k, v in constraints.items() if v]
        lines.append(f"**Constraints:** {', '.join(active) if active else '_none detected_'}")
        lines.append(f"**Dominant:** {pf.get('dominant_constraint') or '_not specified_'}")
        lines.append("")

        # Section 12: Unique Mechanism
        lines.append("### 12. Unique Mechanism")
        um = belief.unique_mechanism
        ump = um.get("ump", {})
        lines.append("**UMP:**")
        lines.append(f"- Old Explanation: {ump.get('old_accepted_explanation') or '_not specified_'}")
        lines.append(f"- Reframed Root Cause: {ump.get('reframed_root_cause') or '_not specified_'}")
        lines.append(f"- Why Past Failed: {ump.get('why_past_solutions_failed') or '_not specified_'}")
        lines.append(f"- Missing 1%: {ump.get('missing_1_percent') or '_not specified_'}")
        lines.append("")

        ums = um.get("ums", {})
        lines.append("**UMS:**")
        lines.append(f"- Macro Logic: {ums.get('macro_solution_logic') or '_not specified_'}")
        lines.append(f"- Micro Mechanism: {ums.get('micro_mechanism') or '_not specified_'}")
        lines.append("")

        # Section 13-15: Abbreviated
        lines.append("### 13-15. Progress, Proof Stack, Expression")
        expr = belief.expression
        lines.append(f"- **Hook:** {expr.get('core_hook') or '_not specified_'}")
        lines.append(f"- **Angle:** {expr.get('primary_angle') or '_not specified_'}")
        lines.append("")

        return lines

    def _render_integrity_checks(
        self,
        checks: List[IntegrityCheckResult]
    ) -> List[str]:
        """Render integrity check results."""
        lines = []
        lines.append("## Integrity Check")
        lines.append("")

        for check in checks:
            status = "PASS" if check.passed else "FAIL"
            icon = "[x]" if check.passed else "[ ]"
            lines.append(f"- {icon} **{check.check_name}**: {status}")
            if check.notes:
                lines.append(f"  - {check.notes}")

        lines.append("")
        return lines

    # =========================================================================
    # CANVAS UPDATE WITH RESEARCH
    # =========================================================================

    async def update_canvas_with_research(
        self,
        draft_canvas: Dict[str, Any],
        reddit_bundle: Dict[str, Any],
        product_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Update draft canvas with Reddit research findings.

        Args:
            draft_canvas: The draft canvas assembled from messages
            reddit_bundle: RedditResearchBundle with extracted signals
            product_context: Product context for reference

        Returns:
            Updated canvas dict with OBSERVED data from research
        """
        # Start with the draft canvas
        updated = dict(draft_canvas)

        # Ensure canvas structure exists
        if "research_canvas" not in updated:
            updated["research_canvas"] = {}
        if "belief_canvas" not in updated:
            updated["belief_canvas"] = {}

        rc = updated["research_canvas"]
        bc = updated["belief_canvas"]

        # Update observed pain from extracted_pain
        extracted_pain = reddit_bundle.get("extracted_pain", [])
        if extracted_pain:
            if "observed_pain" not in rc:
                rc["observed_pain"] = {}

            symptoms_physical = []
            symptoms_emotional = []
            stated_problems = []

            for pain in extracted_pain:
                if isinstance(pain, dict):
                    # Handle both old format (type/description) and new format (signal_type/signal)
                    pain_type = (pain.get("signal_type") or pain.get("type") or "").lower()
                    description = pain.get("signal") or pain.get("description") or ""

                    if not description:
                        continue  # Skip empty entries

                    if "physical" in pain_type or "body" in pain_type:
                        symptoms_physical.append(description)
                    elif "emotional" in pain_type or "mental" in pain_type:
                        symptoms_emotional.append(description)
                    else:
                        stated_problems.append(description)
                elif isinstance(pain, str) and pain:
                    stated_problems.append(pain)

            if symptoms_physical:
                rc["observed_pain"]["symptoms_physical"] = symptoms_physical
            if symptoms_emotional:
                rc["observed_pain"]["symptoms_emotional"] = symptoms_emotional
            if stated_problems:
                rc["observed_pain"]["stated_problems"] = stated_problems

        # Update pattern detection
        pattern_data = reddit_bundle.get("pattern_detection", {})
        if pattern_data:
            if "pattern_detection" not in rc:
                rc["pattern_detection"] = {}

            if pattern_data.get("triggers"):
                rc["pattern_detection"]["triggers"] = pattern_data["triggers"]
            if pattern_data.get("worsens"):
                rc["pattern_detection"]["worsens"] = pattern_data["worsens"]
            if pattern_data.get("improves"):
                rc["pattern_detection"]["improves"] = pattern_data["improves"]
            if pattern_data.get("fails"):
                rc["pattern_detection"]["what_reliably_fails"] = pattern_data["fails"]

        # Update solutions attempted
        solutions = reddit_bundle.get("extracted_solutions_attempted", [])
        if solutions:
            if "solutions_attempted" not in rc:
                rc["solutions_attempted"] = {}

            worked_briefly = []
            stopped_working = []
            never_worked = []
            failure_reasons = []

            for sol in solutions:
                if isinstance(sol, dict):
                    outcome = (sol.get("outcome") or "").lower()
                    # Handle both old format (description) and new format (signal)
                    description = sol.get("signal") or sol.get("description") or ""
                    reason = sol.get("why_failed") or ""

                    if not description:
                        continue  # Skip empty entries

                    if "stopped" in outcome or "stop" in outcome:
                        stopped_working.append(description)
                    elif "worked" in outcome or "briefly" in outcome:
                        worked_briefly.append(description)
                    elif "never" in outcome or "didn't" in outcome:
                        never_worked.append(description)
                    else:
                        # Default to worked_briefly if unclear
                        worked_briefly.append(description)

                    if reason:
                        failure_reasons.append(reason)

            if worked_briefly:
                rc["solutions_attempted"]["worked_briefly"] = worked_briefly
            if stopped_working:
                rc["solutions_attempted"]["stopped_working"] = stopped_working
            if never_worked:
                rc["solutions_attempted"]["never_worked"] = never_worked
            if failure_reasons:
                rc["solutions_attempted"]["failure_reasons"] = failure_reasons

        # Update JTBD candidates in belief canvas
        jtbd_candidates = reddit_bundle.get("jtbd_candidates", {})
        if jtbd_candidates:
            if "persona_filter" not in bc:
                bc["persona_filter"] = {}
            if "jtbd" not in bc["persona_filter"]:
                bc["persona_filter"]["jtbd"] = {}

            for key in ["functional", "emotional", "identity"]:
                if jtbd_candidates.get(key):
                    # Take first candidate if list
                    candidate = jtbd_candidates[key]
                    if isinstance(candidate, list) and candidate:
                        candidate = candidate[0]
                    bc["persona_filter"]["jtbd"][key] = candidate

        # Update language bank
        language_bank = reddit_bundle.get("extracted_language_bank", {})
        if language_bank:
            if "desired_progress" not in rc:
                rc["desired_progress"] = {}
            rc["desired_progress"]["customer_language"] = language_bank

        # Strengthen UMP with research
        if "unique_mechanism" not in bc:
            bc["unique_mechanism"] = {}
        if "ump" not in bc["unique_mechanism"]:
            bc["unique_mechanism"]["ump"] = {}

        ump = bc["unique_mechanism"]["ump"]

        # Why past solutions failed - from research
        if solutions and not ump.get("why_past_solutions_failed"):
            failure_summaries = []
            for sol in solutions:
                if isinstance(sol, dict) and sol.get("why_failed"):
                    failure_summaries.append(sol["why_failed"])
            if failure_summaries:
                ump["why_past_solutions_failed"] = "; ".join(failure_summaries[:3])

        # Externalized blame - use customer language
        if pattern_data.get("fails") and not ump.get("externalized_blame"):
            # Look for "not your fault" type patterns
            blame_phrases = pattern_data.get("fails", [])
            if blame_phrases:
                ump["externalized_blame"] = f"It's not about willpower - it's because {blame_phrases[0]}"

        return updated


# =============================================================================
# PROMPT GETTERS (for pipeline nodes)
# =============================================================================

def get_parse_messages_prompt() -> str:
    """Get the system prompt for message parsing."""
    return PARSE_MESSAGES_SYSTEM_PROMPT


def get_layer_classifier_prompt() -> str:
    """Get the system prompt for layer classification."""
    return LAYER_CLASSIFIER_SYSTEM_PROMPT


def get_draft_canvas_prompt() -> str:
    """Get the system prompt for draft canvas assembly."""
    return DRAFT_CANVAS_SYSTEM_PROMPT


def get_research_extractor_prompt() -> str:
    """Get the system prompt for research extraction."""
    return RESEARCH_EXTRACTOR_SYSTEM_PROMPT


def get_claim_risk_prompt() -> str:
    """Get the system prompt for claim risk detection."""
    return CLAIM_RISK_SYSTEM_PROMPT


# =============================================================================
# CANVAS UPDATE PROMPT
# =============================================================================

CANVAS_UPDATE_SYSTEM_PROMPT = """You are updating a Belief-First Master Canvas with research findings from Reddit.

You have:
1. A draft canvas (with INFERRED data from messages)
2. A Reddit research bundle (with OBSERVED data from real conversations)

Your job is to:
1. Update sections 1-9 (Research Canvas) with observed evidence
2. Strengthen section 12 (UMP) with real customer language
3. Promote "hypothesis" data to "observed" where evidence supports

## Update Rules:
- OBSERVED evidence takes precedence over INFERRED
- Use actual customer language when available
- Keep hypothesis items that aren't contradicted by research
- Add patterns, triggers, and failure reasons from Reddit
- Update JTBD candidates based on what people actually want

## Key Updates to Make:

### Research Canvas (Sections 1-9)
- observed_pain: Add symptoms from extracted_pain
- pattern_detection: Add patterns from research
- solutions_attempted: Add from extracted_solutions_attempted
- candidate_root_causes: Derive from failure patterns

### Belief Canvas (Section 12 - UMP)
- old_accepted_explanation: What Reddit users think causes the problem
- reframed_root_cause: Pattern from research that reveals the real cause
- why_past_solutions_failed: From extracted_solutions_attempted
- externalized_blame: Customer language for "it's not your fault"

Return the complete updated canvas JSON."""


# =============================================================================
# INSIGHT SYNTHESIS - Angle Pipeline Integration
# =============================================================================

class InsightSynthesizer:
    """
    Synthesizes Reddit research signals into angle candidates.

    Used by InsightSynthesisNode to:
    1. Extract pain signals → pain_signal candidates
    2. Extract patterns → pattern candidates
    3. Extract JTBD → jtbd candidates
    4. Handle deduplication via similarity checking
    """

    def __init__(self, angle_candidate_service=None):
        """
        Initialize with optional service injection.

        Args:
            angle_candidate_service: AngleCandidateService instance (lazy loaded if not provided)
        """
        self._angle_candidate_service = angle_candidate_service

    @property
    def angle_service(self):
        """Lazy-load AngleCandidateService to avoid circular imports."""
        if self._angle_candidate_service is None:
            from .angle_candidate_service import AngleCandidateService
            self._angle_candidate_service = AngleCandidateService()
        return self._angle_candidate_service

    def synthesize_candidates_from_bundle(
        self,
        reddit_bundle: Dict[str, Any],
        product_id,
        source_run_id=None,
        brand_id=None,
    ) -> Dict[str, Any]:
        """
        Extract angle candidates from a reddit_bundle.

        Args:
            reddit_bundle: RedditResearchBundle dict with extracted signals
            product_id: Product UUID
            source_run_id: Optional run ID for tracing
            brand_id: Optional brand UUID

        Returns:
            Dict with:
                - candidates_created: int
                - candidates_updated: int (existing candidates with new evidence)
                - candidates: list of created/updated AngleCandidate dicts
                - by_type: dict counting candidates by type
        """
        from uuid import UUID

        # Convert to UUID if string
        if isinstance(product_id, str):
            product_id = UUID(product_id)
        if source_run_id and isinstance(source_run_id, str):
            source_run_id = UUID(source_run_id)
        if brand_id and isinstance(brand_id, str):
            brand_id = UUID(brand_id)

        results = {
            "candidates_created": 0,
            "candidates_updated": 0,
            "candidates": [],
            "by_type": {},
        }

        if not reddit_bundle:
            logger.warning("Empty reddit_bundle, no candidates to create")
            return results

        # 1. Extract pain signals
        pain_results = self._extract_pain_candidates(
            reddit_bundle.get("extracted_pain", []),
            product_id, source_run_id, brand_id
        )
        results["candidates"].extend(pain_results["candidates"])
        results["candidates_created"] += pain_results["created"]
        results["candidates_updated"] += pain_results["updated"]
        results["by_type"]["pain_signal"] = pain_results["created"] + pain_results["updated"]

        # 2. Extract pattern candidates
        pattern_results = self._extract_pattern_candidates(
            reddit_bundle.get("pattern_detection", {}),
            product_id, source_run_id, brand_id
        )
        results["candidates"].extend(pattern_results["candidates"])
        results["candidates_created"] += pattern_results["created"]
        results["candidates_updated"] += pattern_results["updated"]
        results["by_type"]["pattern"] = pattern_results["created"] + pattern_results["updated"]

        # 3. Extract JTBD candidates
        jtbd_results = self._extract_jtbd_candidates(
            reddit_bundle.get("jtbd_candidates", {}),
            product_id, source_run_id, brand_id
        )
        results["candidates"].extend(jtbd_results["candidates"])
        results["candidates_created"] += jtbd_results["created"]
        results["candidates_updated"] += jtbd_results["updated"]
        results["by_type"]["jtbd"] = jtbd_results["created"] + jtbd_results["updated"]

        # 4. Extract solution failure candidates (these inform UMP)
        solution_results = self._extract_solution_failure_candidates(
            reddit_bundle.get("extracted_solutions_attempted", []),
            product_id, source_run_id, brand_id
        )
        results["candidates"].extend(solution_results["candidates"])
        results["candidates_created"] += solution_results["created"]
        results["candidates_updated"] += solution_results["updated"]
        results["by_type"]["ump"] = solution_results["created"] + solution_results["updated"]

        logger.info(
            f"Synthesized {results['candidates_created']} new candidates, "
            f"updated {results['candidates_updated']} existing"
        )

        return results

    def _extract_pain_candidates(
        self,
        extracted_pain: List[Dict],
        product_id,
        source_run_id,
        brand_id,
    ) -> Dict[str, Any]:
        """Extract pain signals into angle candidates."""
        results = {"candidates": [], "created": 0, "updated": 0}

        for pain in extracted_pain:
            if not pain:
                continue

            # Handle both dict and string formats
            if isinstance(pain, str):
                signal = pain
                signal_type = "general"
            else:
                signal = pain.get("signal") or pain.get("description") or ""
                signal_type = pain.get("signal_type") or pain.get("type") or "general"

            if not signal or len(signal) < 10:
                continue  # Skip empty or too short

            # Build candidate name from signal (truncated)
            name = signal[:50] + "..." if len(signal) > 50 else signal
            belief_statement = signal

            # Check for similar existing candidate
            candidate, was_created = self.angle_service.get_or_create_candidate(
                product_id=product_id,
                belief_statement=belief_statement,
                name=name,
                source_type="belief_reverse_engineer",
                candidate_type="pain_signal",
                brand_id=brand_id,
                source_run_id=source_run_id,
                explanation=f"Pain signal ({signal_type}) from Reddit research",
                tags=[signal_type, "reddit_research"],
            )

            if was_created:
                results["created"] += 1
            else:
                results["updated"] += 1
                # Add evidence to existing candidate
                self.angle_service.add_evidence(
                    candidate_id=candidate.id,
                    evidence_type="pain_signal",
                    evidence_text=belief_statement,
                    source_type="belief_reverse_engineer",
                    source_run_id=source_run_id,
                )

            results["candidates"].append(candidate.model_dump() if hasattr(candidate, 'model_dump') else candidate)

        return results

    def _extract_pattern_candidates(
        self,
        pattern_detection: Dict[str, Any],
        product_id,
        source_run_id,
        brand_id,
    ) -> Dict[str, Any]:
        """Extract patterns (triggers, what helps, what fails) into candidates."""
        results = {"candidates": [], "created": 0, "updated": 0}

        # Process each pattern type
        pattern_types = [
            ("triggers", "What triggers the problem"),
            ("worsens", "What makes it worse"),
            ("improves", "What temporarily improves it"),
            ("helps", "What helps with the problem"),
            ("fails", "What reliably fails"),
        ]

        for pattern_key, pattern_description in pattern_types:
            patterns = pattern_detection.get(pattern_key, [])

            for pattern in patterns:
                if not pattern or len(str(pattern)) < 5:
                    continue

                pattern_str = str(pattern)
                name = f"{pattern_key.title()}: {pattern_str[:40]}"
                belief_statement = f"{pattern_description}: {pattern_str}"

                candidate, was_created = self.angle_service.get_or_create_candidate(
                    product_id=product_id,
                    belief_statement=belief_statement,
                    name=name,
                    source_type="belief_reverse_engineer",
                    candidate_type="pattern",
                    brand_id=brand_id,
                    source_run_id=source_run_id,
                    explanation=f"Pattern ({pattern_key}) from Reddit research",
                    tags=[pattern_key, "pattern", "reddit_research"],
                )

                if was_created:
                    results["created"] += 1
                else:
                    results["updated"] += 1
                    self.angle_service.add_evidence(
                        candidate_id=candidate.id,
                        evidence_type="pattern",
                        evidence_text=pattern_str,
                        source_type="belief_reverse_engineer",
                        source_run_id=source_run_id,
                    )

                results["candidates"].append(candidate.model_dump() if hasattr(candidate, 'model_dump') else candidate)

        return results

    def _extract_jtbd_candidates(
        self,
        jtbd_candidates: Dict[str, Any],
        product_id,
        source_run_id,
        brand_id,
    ) -> Dict[str, Any]:
        """Extract JTBD (functional, emotional, identity) into candidates."""
        results = {"candidates": [], "created": 0, "updated": 0}

        jtbd_types = ["functional", "emotional", "identity"]

        for jtbd_type in jtbd_types:
            jobs = jtbd_candidates.get(jtbd_type, [])

            # Handle both list and single value
            if isinstance(jobs, str):
                jobs = [jobs]
            elif not isinstance(jobs, list):
                continue

            for job in jobs:
                if not job or len(str(job)) < 10:
                    continue

                job_str = str(job)
                name = f"JTBD ({jtbd_type}): {job_str[:40]}"
                belief_statement = f"Job to be done ({jtbd_type}): {job_str}"

                candidate, was_created = self.angle_service.get_or_create_candidate(
                    product_id=product_id,
                    belief_statement=belief_statement,
                    name=name,
                    source_type="belief_reverse_engineer",
                    candidate_type="jtbd",
                    brand_id=brand_id,
                    source_run_id=source_run_id,
                    explanation=f"JTBD ({jtbd_type}) from Reddit research",
                    tags=[jtbd_type, "jtbd", "reddit_research"],
                )

                if was_created:
                    results["created"] += 1
                else:
                    results["updated"] += 1
                    self.angle_service.add_evidence(
                        candidate_id=candidate.id,
                        evidence_type="jtbd",
                        evidence_text=job_str,
                        source_type="belief_reverse_engineer",
                        source_run_id=source_run_id,
                    )

                results["candidates"].append(candidate.model_dump() if hasattr(candidate, 'model_dump') else candidate)

        return results

    def _extract_solution_failure_candidates(
        self,
        solutions_attempted: List[Dict],
        product_id,
        source_run_id,
        brand_id,
    ) -> Dict[str, Any]:
        """Extract solution failures into UMP candidates (explains why past solutions failed)."""
        results = {"candidates": [], "created": 0, "updated": 0}

        for solution in solutions_attempted:
            if not solution:
                continue

            # Handle both dict and string formats
            if isinstance(solution, str):
                description = solution
                why_failed = ""
            else:
                description = solution.get("signal") or solution.get("description") or ""
                why_failed = solution.get("why_failed") or ""

            if not description and not why_failed:
                continue

            # The "why it failed" insight is valuable for UMP
            if why_failed and len(why_failed) >= 10:
                name = f"Why failed: {why_failed[:40]}"
                belief_statement = f"Past solutions failed because: {why_failed}"

                candidate, was_created = self.angle_service.get_or_create_candidate(
                    product_id=product_id,
                    belief_statement=belief_statement,
                    name=name,
                    source_type="belief_reverse_engineer",
                    candidate_type="ump",
                    brand_id=brand_id,
                    source_run_id=source_run_id,
                    explanation=f"UMP insight (why past solutions failed) from Reddit research",
                    tags=["ump", "solution_failure", "reddit_research"],
                )

                if was_created:
                    results["created"] += 1
                else:
                    results["updated"] += 1
                    self.angle_service.add_evidence(
                        candidate_id=candidate.id,
                        evidence_type="solution",
                        evidence_text=f"{description} - Failed because: {why_failed}",
                        source_type="belief_reverse_engineer",
                        source_run_id=source_run_id,
                    )

                results["candidates"].append(candidate.model_dump() if hasattr(candidate, 'model_dump') else candidate)

        return results
