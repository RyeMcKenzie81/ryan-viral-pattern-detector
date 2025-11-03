"""
Blog Generator

Generates blog posts (500-1500 words) from viral hooks.

Takes hook analysis from Phase 2B and expands it into a full blog post
with introduction, body sections, and conclusion.

Usage:
    generator = BlogGenerator(db_connection)
    content = generator.generate(hook_analysis, project_context)
    generator.save_to_db(content)
"""

import logging
from typing import Dict
import json
from datetime import datetime

from .content_generator import ContentGenerator, GeneratedContent


logger = logging.getLogger(__name__)


class BlogGenerator(ContentGenerator):
    """
    Generates blog posts from viral hooks

    Creates 500-1500 word blog posts that:
    - Open with attention-grabbing intro based on viral hook
    - Develop key ideas with examples and insights
    - Provide actionable takeaways
    - End with CTA
    """

    def generate(self,
                 hook_analysis: Dict,
                 project_context: Dict,
                 target_word_count: int = 1000,
                 include_examples: bool = True,
                 tone: str = "conversational") -> GeneratedContent:
        """
        Generate blog post from hook analysis

        Args:
            hook_analysis: Hook analysis from Phase 2B
            project_context: Project info
            target_word_count: Target word count (500-1500)
            include_examples: Include real-world examples
            tone: Writing tone ('conversational', 'professional', 'casual')

        Returns:
            GeneratedContent with blog post
        """
        logger.info(f"Generating blog post from hook: {hook_analysis.get('hook_type')}")

        # Validate word count
        target_word_count = max(500, min(1500, target_word_count))

        # Build prompt
        prompt = self._build_blog_prompt(
            hook_analysis,
            project_context,
            target_word_count,
            include_examples,
            tone
        )

        # Estimate cost
        prompt_tokens = len(prompt.split()) * 1.3
        output_tokens = target_word_count * 1.5  # ~1.5 tokens per word
        estimated_cost = self._estimate_cost(int(prompt_tokens), int(output_tokens))

        # Call Gemini
        logger.debug("Calling Gemini API for blog generation")
        response = self.model.generate_content(prompt)

        # Parse response
        blog_data = self._parse_blog_response(response.text)

        # Create GeneratedContent object
        content = GeneratedContent(
            source_tweet_id=hook_analysis.get('tweet_id'),  # Updated to use tweet_id field
            source_tweet_text=hook_analysis.get('tweet_text', ''),
            hook_type=hook_analysis.get('hook_type', 'unknown'),
            emotional_trigger=hook_analysis.get('emotional_trigger', 'unknown'),
            content_pattern=hook_analysis.get('content_pattern', 'unknown'),
            hook_explanation=hook_analysis.get('hook_explanation', ''),
            adaptation_notes=hook_analysis.get('adaptation_notes', ''),
            content_type='blog',
            content_title=blog_data.get('title', 'Blog Post'),
            content_body=blog_data.get('content', ''),
            content_metadata=blog_data,
            project_id=project_context.get('project_id'),
            project_context=json.dumps(project_context),
            api_cost_usd=estimated_cost,
            model_used=self.model_name,
            status='pending',
            created_at=datetime.now()
        )

        word_count = len(blog_data.get('content', '').split())
        logger.info(f"Generated blog post: {word_count} words")

        return content

    def _build_blog_prompt(self,
                          hook_analysis: Dict,
                          project_context: Dict,
                          target_word_count: int,
                          include_examples: bool,
                          tone: str) -> str:
        """Build AI prompt for blog generation"""

        tweet_text = hook_analysis.get('tweet_text', '')
        hook_type = hook_analysis.get('hook_type', 'unknown')
        emotional_trigger = hook_analysis.get('emotional_trigger', 'unknown')
        hook_explanation = hook_analysis.get('hook_explanation', '')
        adaptation_notes = hook_analysis.get('adaptation_notes', '')

        product_name = project_context.get('product_name', 'our product')
        product_description = project_context.get('product_description', '')
        target_audience = project_context.get('target_audience', 'readers')
        key_benefits = project_context.get('key_benefits', [])

        benefits_text = "\n".join([f"- {b}" for b in key_benefits]) if key_benefits else "N/A"
        examples_instruction = "Include 2-3 real-world examples or case studies" if include_examples else ""

        prompt = f"""You are an expert blog writer who creates engaging, valuable content from viral social media hooks.

SOURCE TWEET (went viral):
"{tweet_text}"

HOOK ANALYSIS:
- Hook type: {hook_type}
- Emotional trigger: {emotional_trigger}
- Why it works: {hook_explanation}
- How to adapt: {adaptation_notes}

PROJECT CONTEXT:
- Product/Service: {product_name}
- Description: {product_description}
- Target audience: {target_audience}
- Key benefits:
{benefits_text}

TASK:
Write a blog post (~{target_word_count} words) that:
1. Opens with an attention-grabbing intro inspired by the viral hook
2. Maintains the "{emotional_trigger}" emotional trigger
3. Develops 3-5 key insights related to the hook's core idea
4. Connects these insights to {product_name} naturally
5. Provides actionable takeaways for {target_audience}
6. Ends with a compelling CTA

STRUCTURE:
- Title: Catchy, SEO-friendly (60-70 characters)
- Introduction: Hook the reader (100-150 words)
- Body: 3-5 sections with H2 headings (600-1200 words total)
- Conclusion: Summary + CTA (100-150 words)

STYLE:
- Tone: {tone}
- Use short paragraphs (2-4 sentences)
- Include bullet points and lists where appropriate
- {examples_instruction}
- Make it scannable and easy to read
- Focus on value and insights, not just promotion

OUTPUT FORMAT (JSON):
{{
  "title": "SEO-Friendly Blog Post Title",
  "subtitle": "Optional subtitle or hook",
  "seo_description": "Meta description (150-160 chars)",
  "content": "Full blog post in markdown format with ## headings",
  "sections": [
    {{"heading": "Section 1", "key_point": "Main takeaway"}},
    {{"heading": "Section 2", "key_point": "Main takeaway"}},
    ...
  ],
  "key_takeaways": ["takeaway 1", "takeaway 2", "takeaway 3"],
  "cta": "Call to action text",
  "word_count": {target_word_count},
  "reading_time_minutes": 5
}}

IMPORTANT:
- Return ONLY valid JSON, no additional text
- Content field should be complete markdown
- Aim for {target_word_count} words (±100 words is fine)
- Make it genuinely valuable, not just promotional
- Adapt the hook naturally, don't force it"""

        return prompt

    def _parse_blog_response(self, response_text: str) -> Dict:
        """
        Parse Gemini response into blog data

        Args:
            response_text: Raw JSON response from Gemini

        Returns:
            Dict with blog data
        """
        try:
            # Clean JSON from markdown code blocks
            json_text = self._clean_json_response(response_text)

            # Try to parse JSON
            try:
                data = json.loads(json_text)
            except json.JSONDecodeError as e:
                # If parsing fails, try with strict=False to handle control characters
                logger.warning(f"Initial JSON parse failed, trying with strict=False: {e}")
                data = json.loads(json_text, strict=False)

            # Validate required fields
            if 'content' not in data:
                raise ValueError("Response missing 'content' field")

            # Calculate actual word count
            actual_word_count = len(data.get('content', '').split())

            return {
                'title': data.get('title', 'Blog Post'),
                'subtitle': data.get('subtitle', ''),
                'seo_description': data.get('seo_description', ''),
                'content': data.get('content', ''),
                'sections': data.get('sections', []),
                'key_takeaways': data.get('key_takeaways', []),
                'cta': data.get('cta', ''),
                'word_count': actual_word_count,
                'reading_time_minutes': data.get('reading_time_minutes', max(1, actual_word_count // 200))
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response text: {response_text[:500]}")
            raise ValueError(f"Invalid JSON response from AI: {e}")

        except Exception as e:
            logger.error(f"Error parsing blog response: {e}")
            raise

    def format_for_wordpress(self, content: GeneratedContent) -> Dict:
        """
        Format blog post for WordPress import

        Args:
            content: GeneratedContent with blog

        Returns:
            WordPress-compatible format
        """
        metadata = content.content_metadata

        return {
            "title": content.content_title,
            "content": metadata.get('content', ''),
            "excerpt": metadata.get('seo_description', ''),
            "status": "draft",
            "meta": {
                "hook_type": content.hook_type,
                "source_tweet": content.source_tweet_text,
                "generated_at": content.created_at.isoformat()
            }
        }

    def format_for_medium(self, content: GeneratedContent) -> str:
        """
        Format blog post for Medium (markdown)

        Args:
            content: GeneratedContent with blog

        Returns:
            Medium-ready markdown
        """
        metadata = content.content_metadata

        lines = [
            f"# {content.content_title}",
            ""
        ]

        if metadata.get('subtitle'):
            lines.append(f"*{metadata.get('subtitle')}*")
            lines.append("")

        lines.append(metadata.get('content', ''))

        return "\n".join(lines)
