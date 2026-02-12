"""
AdAnalysisService - Analyze Facebook ads to extract offer variant messaging.

This service handles:
- Grouping scraped ads by destination URL
- Analyzing ad creatives (images, videos, copy)
- Synthesizing analyses into offer variant messaging data

Used by Client Onboarding to pre-populate offer variants from existing ads.
"""

import logging
import json
import asyncio
import httpx
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable, Set
from dataclasses import dataclass, field
from collections import Counter
from urllib.parse import urlparse, parse_qs

from supabase import Client
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


@dataclass
class AdGroup:
    """Group of ads sharing the same landing page URL."""
    normalized_url: str
    display_url: str  # Original URL for display
    ad_count: int
    ads: List[Dict] = field(default_factory=list)
    preview_text: Optional[str] = None
    preview_image_url: Optional[str] = None


@dataclass
class AdAnalysisResult:
    """Result of analyzing a single ad."""
    ad_id: str
    ad_type: str  # 'image', 'video', 'copy_only'
    copy_analysis: Optional[Dict] = None
    image_analysis: Optional[Dict] = None
    video_analysis: Optional[Dict] = None
    raw_copy: Optional[str] = None


class AdAnalysisService:
    """
    Service for analyzing Facebook ads to extract messaging for offer variants.

    Workflow:
    1. group_ads_by_url() - Group scraped ads by landing page
    2. analyze_ad_group() - Analyze all ads in a group
    3. synthesize_messaging() - Merge analyses into offer variant data
    """

    def __init__(self, supabase: Optional[Client] = None):
        """
        Initialize AdAnalysisService.

        Args:
            supabase: Optional Supabase client. If not provided, creates one.
        """
        self.supabase = supabase or get_supabase_client()

        # Lazy load dependencies to avoid circular imports
        self._brand_research_service = None
        self._ad_scraping_service = None

        logger.info("AdAnalysisService initialized")

    @property
    def brand_research_service(self):
        """Lazy load BrandResearchService."""
        if self._brand_research_service is None:
            from .brand_research_service import BrandResearchService
            self._brand_research_service = BrandResearchService(self.supabase)
        return self._brand_research_service

    @property
    def ad_scraping_service(self):
        """Lazy load AdScrapingService."""
        if self._ad_scraping_service is None:
            from .ad_scraping_service import AdScrapingService
            self._ad_scraping_service = AdScrapingService(self.supabase)
        return self._ad_scraping_service

    # ============================================================
    # URL Grouping
    # ============================================================

    def _resolve_redirect_url(self, url: str) -> str:
        """
        Resolve redirect URLs to their final destination.

        Handles patterns like:
        - /discount/CODE?redirect=/pages/landing
        - /discount/CODE?redirect=%2Fpages%2Flanding (URL-encoded)

        Args:
            url: Original URL that may contain redirect param

        Returns:
            Resolved URL or original if no redirect found
        """
        from urllib.parse import unquote

        parsed = urlparse(url)

        # Check for redirect parameter
        if parsed.query:
            params = parse_qs(parsed.query)
            redirect_value = params.get('redirect', params.get('return_to', params.get('return', [None])))[0]

            if redirect_value:
                # URL-decode the redirect value
                decoded_redirect = unquote(redirect_value)

                # If it's a relative path, combine with base URL
                if decoded_redirect.startswith('/'):
                    resolved = f"{parsed.scheme}://{parsed.netloc}{decoded_redirect}"
                    logger.debug(f"Resolved redirect URL: {url} -> {resolved}")
                    return resolved
                elif decoded_redirect.startswith('http'):
                    # Absolute URL redirect
                    logger.debug(f"Resolved redirect URL: {url} -> {decoded_redirect}")
                    return decoded_redirect

        return url

    def _normalize_url(self, url: str) -> str:
        """
        Normalize URL for grouping (remove tracking params, www, trailing slash).

        Note: Call _resolve_redirect_url() first if you need to resolve redirects.

        Args:
            url: URL to normalize

        Returns:
            Normalized URL string
        """
        if not url:
            return ""

        parsed = urlparse(url.lower())

        # Remove www. prefix
        netloc = parsed.netloc
        if netloc.startswith('www.'):
            netloc = netloc[4:]

        # Remove tracking parameters
        tracking_params = {
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_content',
            'utm_term', 'fbclid', 'gclid', 'ref', 'source', 'mc_cid',
            'mc_eid', 'affid', 'click_id', 'clickid'
        }

        if parsed.query:
            params = parse_qs(parsed.query)
            filtered_params = {
                k: v for k, v in params.items()
                if k.lower() not in tracking_params
            }
            query = '&'.join(f"{k}={v[0]}" for k, v in sorted(filtered_params.items()))
        else:
            query = ''

        path = parsed.path.rstrip('/')

        if query:
            return f"{netloc}{path}?{query}"
        else:
            return f"{netloc}{path}"

    def _extract_url_from_snapshot(self, snapshot: Dict) -> Optional[str]:
        """
        Extract landing page URL from ad snapshot.

        Args:
            snapshot: Ad snapshot dict

        Returns:
            Landing page URL or None
        """
        if not snapshot or not isinstance(snapshot, dict):
            return None

        # Try direct link_url field
        if 'link_url' in snapshot:
            return snapshot['link_url']

        # Check cards for carousel ads
        if 'cards' in snapshot and snapshot['cards']:
            for card in snapshot['cards']:
                if 'link_url' in card:
                    return card['link_url']

        # Check cta_link
        if 'cta_link' in snapshot:
            return snapshot['cta_link']

        return None

    def _extract_copy_from_snapshot(self, snapshot: Dict) -> str:
        """
        Extract ad copy text from snapshot.

        Args:
            snapshot: Ad snapshot dict

        Returns:
            Ad copy text
        """
        if not snapshot or not isinstance(snapshot, dict):
            return ""

        parts = []

        # Body text (nested in body.text)
        body_obj = snapshot.get("body", {})
        if isinstance(body_obj, dict) and body_obj.get("text"):
            parts.append(body_obj["text"])

        # Title
        if snapshot.get("title"):
            parts.append(snapshot["title"])

        # Caption
        if snapshot.get("caption"):
            parts.append(snapshot["caption"])

        # Link description
        if snapshot.get("link_description"):
            parts.append(snapshot["link_description"])

        # Cards (carousel) - get copy from each
        for card in snapshot.get("cards", []):
            if card.get("title"):
                parts.append(card["title"])
            if card.get("body"):
                body = card["body"]
                if isinstance(body, dict):
                    parts.append(body.get("text", ""))
                elif isinstance(body, str):
                    parts.append(body)

        return "\n\n".join(filter(None, parts))

    def _get_preview_image(self, snapshot: Dict) -> Optional[str]:
        """Get first available image URL from snapshot for preview."""
        assets = self.ad_scraping_service.extract_asset_urls(snapshot)
        if assets.get("images"):
            return assets["images"][0]
        return None

    def group_ads_by_url(self, ads: List[Dict]) -> List[AdGroup]:
        """
        Group ads by normalized destination URL.

        Args:
            ads: List of ad records with 'id' and 'snapshot' fields

        Returns:
            List of AdGroup objects sorted by ad count (descending)
        """
        url_groups: Dict[str, AdGroup] = {}

        for ad in ads:
            ad_id = ad.get('id')
            snapshot = ad.get('snapshot', {})

            # Parse snapshot if string
            if isinstance(snapshot, str):
                try:
                    snapshot = json.loads(snapshot)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse snapshot for ad {ad_id}")
                    continue

            url = self._extract_url_from_snapshot(snapshot)
            if not url:
                continue

            # Resolve any redirect URLs first (e.g., /discount/CODE?redirect=/pages/landing)
            resolved_url = self._resolve_redirect_url(url)

            # Normalize for grouping (removes tracking params, www, etc.)
            normalized = self._normalize_url(resolved_url)
            if not normalized:
                continue

            if normalized not in url_groups:
                url_groups[normalized] = AdGroup(
                    normalized_url=normalized,
                    display_url=resolved_url,  # Use resolved URL for display
                    ad_count=0,
                    ads=[],
                    preview_text=self._extract_copy_from_snapshot(snapshot)[:150],
                    preview_image_url=self._get_preview_image(snapshot)
                )

            group = url_groups[normalized]
            group.ad_count += 1
            group.ads.append({
                'id': ad_id,
                'ad_archive_id': ad.get('ad_archive_id'),  # Preserve for resume tracking
                'snapshot': snapshot,
                'copy': self._extract_copy_from_snapshot(snapshot)
            })

        # Sort by ad count descending
        groups = list(url_groups.values())
        groups.sort(key=lambda g: g.ad_count, reverse=True)

        logger.info(f"Grouped {len(ads)} ads into {len(groups)} URL groups")
        return groups

    # ============================================================
    # Ad Analysis
    # ============================================================

    async def _download_image(self, url: str, timeout: float = 30.0) -> Optional[bytes]:
        """Download image from URL."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.content
        except Exception as e:
            logger.warning(f"Failed to download image: {e}")
            return None

    async def _analyze_single_ad(
        self,
        ad: Dict,
        analyze_images: bool = True,
        analyze_videos: bool = True,
        max_images: int = 2,
        max_videos: int = 1
    ) -> AdAnalysisResult:
        """
        Analyze a single ad (copy, images, videos).

        Args:
            ad: Ad dict with 'id', 'snapshot', 'copy' fields
            analyze_images: Whether to analyze images
            analyze_videos: Whether to analyze videos
            max_images: Max images to analyze per ad
            max_videos: Max videos to analyze per ad

        Returns:
            AdAnalysisResult with all analyses
        """
        ad_id = ad.get('id', 'unknown')
        ad_archive_id = ad.get('ad_archive_id') or ad_id  # Use ad_archive_id for tracking
        snapshot = ad.get('snapshot', {})
        copy_text = ad.get('copy', '')

        result = AdAnalysisResult(
            ad_id=ad_id,
            ad_type='copy_only',
            raw_copy=copy_text
        )

        # Analyze copy
        if copy_text and len(copy_text.strip()) > 20:
            try:
                result.copy_analysis = self.brand_research_service.analyze_copy_sync(
                    ad_copy=copy_text,
                    headline=snapshot.get('title'),
                    ad_id=ad_archive_id,  # Pass ad_archive_id for resume tracking
                    brand_id=None
                )
            except Exception as e:
                logger.warning(f"Copy analysis failed for ad {ad_id}: {e}")

        # Extract asset URLs
        assets = self.ad_scraping_service.extract_asset_urls(snapshot)
        image_urls = assets.get('images', [])[:max_images]
        video_urls = assets.get('videos', [])[:max_videos]

        # Analyze images
        if analyze_images and image_urls:
            result.ad_type = 'image'
            for url in image_urls:
                try:
                    image_bytes = await self._download_image(url)
                    if image_bytes:
                        analysis = self.brand_research_service.analyze_image_sync(
                            image_bytes=image_bytes,
                            skip_save=True
                        )
                        if analysis and not analysis.get('error'):
                            result.image_analysis = analysis
                            break  # Use first successful analysis
                except Exception as e:
                    logger.warning(f"Image analysis failed for ad {ad_id}: {e}")

        # Analyze videos
        if analyze_videos and video_urls:
            result.ad_type = 'video'
            for url in video_urls:
                try:
                    analysis = await self.brand_research_service.analyze_video_from_url(
                        video_url=url,
                        facebook_ad_id=None,
                        brand_id=None,
                        ad_archive_id=ad_archive_id  # Pass for resume tracking
                    )
                    if analysis and not analysis.get('error'):
                        result.video_analysis = analysis
                        break  # Use first successful analysis
                except Exception as e:
                    logger.warning(f"Video analysis failed for ad {ad_id}: {e}")

        return result

    def _get_analyzed_ad_ids(self, ad_archive_ids: List[str]) -> Set[str]:
        """
        Query which ads have already been analyzed.

        Used for resume functionality - skip ads that were analyzed in a previous run.

        Args:
            ad_archive_ids: List of ad_archive_id strings to check

        Returns:
            Set of ad_archive_ids that have already been analyzed
        """
        if not ad_archive_ids:
            return set()

        try:
            result = self.brand_research_service.supabase.table("brand_ad_analysis").select(
                "ad_archive_id"
            ).in_("ad_archive_id", ad_archive_ids).execute()

            return {r['ad_archive_id'] for r in (result.data or []) if r.get('ad_archive_id')}
        except Exception as e:
            logger.warning(f"Failed to query analyzed ads: {e}")
            return set()

    def _fetch_existing_analyses(self, ad_archive_ids: List[str]) -> List[Dict]:
        """
        Fetch previously saved analyses from database.

        Used for resume functionality - include analyses from previous runs in synthesis.

        Args:
            ad_archive_ids: List of ad_archive_id strings to fetch

        Returns:
            List of analysis dicts matching the format from _analysis_to_dict()
        """
        if not ad_archive_ids:
            return []

        try:
            result = self.brand_research_service.supabase.table("brand_ad_analysis").select(
                "ad_archive_id, analysis_type, raw_response"
            ).in_("ad_archive_id", ad_archive_ids).execute()

            # Group by ad_archive_id to combine copy/video/image analyses
            analyses_by_id: Dict[str, Dict] = {}
            for record in (result.data or []):
                ad_id = record.get('ad_archive_id')
                if not ad_id:
                    continue

                if ad_id not in analyses_by_id:
                    analyses_by_id[ad_id] = {
                        'ad_id': ad_id,
                        'ad_type': 'unknown',
                        'copy_analysis': None,
                        'image_analysis': None,
                        'video_analysis': None,
                        'raw_copy': None,
                        '_from_resume': True  # Mark as fetched from previous run
                    }

                analysis_type = record.get('analysis_type', '')
                raw_response = record.get('raw_response', {})

                if analysis_type == 'copy_analysis':
                    analyses_by_id[ad_id]['copy_analysis'] = raw_response
                    analyses_by_id[ad_id]['ad_type'] = 'copy'
                elif analysis_type == 'video_analysis':
                    analyses_by_id[ad_id]['video_analysis'] = raw_response
                    analyses_by_id[ad_id]['ad_type'] = 'video'
                elif analysis_type == 'image_analysis':
                    analyses_by_id[ad_id]['image_analysis'] = raw_response
                    if analyses_by_id[ad_id]['ad_type'] != 'video':
                        analyses_by_id[ad_id]['ad_type'] = 'image'

            logger.info(f"Fetched {len(analyses_by_id)} existing analyses from database")
            return list(analyses_by_id.values())

        except Exception as e:
            logger.warning(f"Failed to fetch existing analyses: {e}")
            return []

    async def analyze_ad_group(
        self,
        ad_group: AdGroup,
        max_ads: int = 10,
        analyze_images: bool = True,
        analyze_videos: bool = True,
        force_reanalyze: bool = False,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Analyze all ads in a group to extract messaging.

        For each ad:
        1. Extract copy from snapshot
        2. Download and analyze image/video assets
        3. Collect: hooks, pain points, desires, benefits

        Args:
            ad_group: AdGroup with ads to analyze
            max_ads: Maximum ads to analyze per group
            analyze_images: Whether to analyze images
            analyze_videos: Whether to analyze videos
            force_reanalyze: If True, re-analyze even if already analyzed
            progress_callback: Optional callback(current, total, status_msg)

        Returns:
            Dict with all individual analyses and metadata
        """
        candidate_ads = ad_group.ads[:max_ads]

        # Check which ads have already been analyzed (for resume functionality)
        ad_archive_ids = [
            ad.get('ad_archive_id') or ad.get('id')
            for ad in candidate_ads
        ]

        if force_reanalyze:
            # Skip resume check - analyze all ads fresh
            already_analyzed = set()
            ads_to_analyze = candidate_ads
        else:
            already_analyzed = self._get_analyzed_ad_ids(ad_archive_ids)
            # Filter to only ads that still need analysis
            ads_to_analyze = [
                ad for ad in candidate_ads
                if (ad.get('ad_archive_id') or ad.get('id')) not in already_analyzed
            ]

        skipped_count = len(already_analyzed)
        total = len(ads_to_analyze)
        analyses: List[AdAnalysisResult] = []

        if skipped_count > 0:
            logger.info(f"Resuming analysis for URL: {ad_group.normalized_url} - "
                       f"{skipped_count} already done, {total} remaining")
        else:
            logger.info(f"Analyzing {total} ads for URL: {ad_group.normalized_url}")

        for i, ad in enumerate(ads_to_analyze):
            if progress_callback:
                # Show progress including skipped count for accurate tracking
                progress_callback(
                    skipped_count + i + 1,
                    skipped_count + total,
                    f"Analyzing ad {i + 1}/{total}" + (f" ({skipped_count} resumed)" if skipped_count else "")
                )

            try:
                result = await self._analyze_single_ad(
                    ad,
                    analyze_images=analyze_images,
                    analyze_videos=analyze_videos
                )
                analyses.append(result)
            except Exception as e:
                logger.error(f"Failed to analyze ad {ad.get('id')}: {e}")

            # Small delay to avoid rate limits
            if i < total - 1:
                await asyncio.sleep(1)

        return {
            'url': ad_group.normalized_url,
            'display_url': ad_group.display_url,
            'total_ads': ad_group.ad_count,
            'analyzed_ads': len(analyses),
            'skipped_ads': skipped_count,  # Resume tracking
            'already_analyzed_ids': list(already_analyzed),  # For fetching existing analyses
            'analyses': [self._analysis_to_dict(a) for a in analyses],
            'source_ad_ids': [a.ad_id for a in analyses]
        }

    def _analysis_to_dict(self, analysis: AdAnalysisResult) -> Dict:
        """Convert AdAnalysisResult to dict."""
        return {
            'ad_id': analysis.ad_id,
            'ad_type': analysis.ad_type,
            'copy_analysis': analysis.copy_analysis,
            'image_analysis': analysis.image_analysis,
            'video_analysis': analysis.video_analysis,
            'raw_copy': analysis.raw_copy
        }

    # ============================================================
    # Messaging Synthesis
    # ============================================================

    def synthesize_messaging(self, analysis_result: Dict) -> Dict[str, Any]:
        """
        Merge multiple ad analyses into unified offer variant messaging.

        Extracts:
        - Most common pain points
        - Most common desires/goals
        - Key benefits mentioned
        - Suggested variant name
        - Sample hooks
        - Target audience

        Args:
            analysis_result: Output from analyze_ad_group()

        Returns:
            Dict with synthesized messaging for offer variant
        """
        analyses = analysis_result.get('analyses', [])

        if not analyses:
            return self._empty_synthesis(analysis_result)

        # Collect all extracted data
        all_pain_points = []
        all_desires = []
        all_benefits = []
        all_hooks = []
        all_claims = []
        all_target_audiences = []
        all_ctas = []
        all_mechanisms = []  # Unique mechanisms mentioned
        all_root_causes = []  # UMP - why other solutions failed
        all_mechanism_solutions = []  # UMS - how mechanism solves problem

        for a in analyses:
            # From copy analysis
            if a.get('copy_analysis'):
                copy = a['copy_analysis']

                # Handle pain_points - can be nested dict or flat list
                pain_points_data = copy.get('pain_points', [])
                if isinstance(pain_points_data, dict):
                    # Nested: {"emotional": [...], "functional": [...]}
                    all_pain_points.extend(pain_points_data.get('emotional', []))
                    all_pain_points.extend(pain_points_data.get('functional', []))
                elif isinstance(pain_points_data, list):
                    all_pain_points.extend(pain_points_data)

                # Also extract from transformation.before (pain states)
                transformation = copy.get('transformation', {})
                if isinstance(transformation, dict):
                    all_pain_points.extend(transformation.get('before', []))
                    all_benefits.extend(transformation.get('after', []))

                # Handle desires - can be nested dict or flat list
                desires_data = copy.get('desires_appealed_to') or copy.get('desires', [])
                if isinstance(desires_data, dict):
                    # Nested: {"care_protection": [...], "freedom_from_fear": [...], ...}
                    for category_values in desires_data.values():
                        if isinstance(category_values, list):
                            all_desires.extend(category_values)
                elif isinstance(desires_data, list):
                    all_desires.extend(desires_data)

                # Handle benefits - can be nested dict or flat list
                benefits_data = copy.get('benefits_outcomes') or copy.get('benefits', [])
                if isinstance(benefits_data, dict):
                    all_benefits.extend(benefits_data.get('emotional', []))
                    all_benefits.extend(benefits_data.get('functional', []))
                elif isinstance(benefits_data, list):
                    all_benefits.extend(benefits_data)

                # Handle hooks - can be dict with text or list
                hook_data = copy.get('hook')
                if isinstance(hook_data, dict) and hook_data.get('text'):
                    all_hooks.append(hook_data['text'])
                elif isinstance(hook_data, str):
                    all_hooks.append(hook_data)
                hooks_list = copy.get('hooks', [])
                if isinstance(hooks_list, list):
                    all_hooks.extend(hooks_list)

                # Handle claims
                claims_data = copy.get('claims_made') or copy.get('claims', [])
                if isinstance(claims_data, list):
                    all_claims.extend(claims_data)

                # Target audience/persona
                target_persona = copy.get('target_persona') or copy.get('target_audience')
                if target_persona:
                    if isinstance(target_persona, dict):
                        # Build audience string from persona dict
                        parts = []
                        if target_persona.get('age_range'):
                            parts.append(target_persona['age_range'])
                        if target_persona.get('gender_focus'):
                            parts.append(target_persona['gender_focus'])
                        if target_persona.get('lifestyle'):
                            parts.extend(target_persona['lifestyle'][:2])
                        if parts:
                            all_target_audiences.append(', '.join(parts))
                    else:
                        all_target_audiences.append(str(target_persona))

                # CTA
                cta = copy.get('call_to_action') or copy.get('cta')
                if cta:
                    all_ctas.append(cta)
                # Mechanism-related fields
                if copy.get('mechanism') or copy.get('unique_mechanism'):
                    all_mechanisms.append(copy.get('mechanism') or copy.get('unique_mechanism'))
                if copy.get('root_cause') or copy.get('why_others_fail'):
                    all_root_causes.append(copy.get('root_cause') or copy.get('why_others_fail'))
                if copy.get('mechanism_solution') or copy.get('how_it_works'):
                    all_mechanism_solutions.append(copy.get('mechanism_solution') or copy.get('how_it_works'))

            # From image analysis
            if a.get('image_analysis'):
                img = a['image_analysis']
                # Image analysis structure may differ - extract what's available
                if img.get('messaging'):
                    msg = img['messaging']
                    all_pain_points.extend(msg.get('pain_points', []))
                    all_benefits.extend(msg.get('benefits', []))
                    all_claims.extend(msg.get('claims', []))
                    # Mechanism-related fields from image
                    if msg.get('mechanism'):
                        all_mechanisms.append(msg['mechanism'])
                    if msg.get('root_cause'):
                        all_root_causes.append(msg['root_cause'])
                if img.get('text_overlays'):
                    for overlay in img['text_overlays']:
                        if overlay.get('text'):
                            # Check if it looks like a hook
                            text = overlay['text']
                            if '?' in text or text.lower().startswith(('are you', 'do you', 'did you', 'have you')):
                                all_hooks.append(text)

            # From video analysis
            if a.get('video_analysis'):
                vid = a['video_analysis']
                if vid.get('messaging'):
                    msg = vid['messaging']
                    all_pain_points.extend(msg.get('pain_points', []))
                    all_desires.extend(msg.get('desires', []))
                    all_benefits.extend(msg.get('benefits', []))
                    all_claims.extend(msg.get('claims', []))
                    # Mechanism-related fields from video
                    if msg.get('mechanism'):
                        all_mechanisms.append(msg['mechanism'])
                    if msg.get('root_cause'):
                        all_root_causes.append(msg['root_cause'])
                    if msg.get('mechanism_solution') or msg.get('how_it_works'):
                        all_mechanism_solutions.append(msg.get('mechanism_solution') or msg.get('how_it_works'))
                if vid.get('hook'):
                    hook = vid['hook']
                    if isinstance(hook, dict) and hook.get('text'):
                        all_hooks.append(hook['text'])
                    elif isinstance(hook, str):
                        all_hooks.append(hook)
                if vid.get('cta'):
                    all_ctas.append(vid['cta'])
                if vid.get('target_audience'):
                    all_target_audiences.append(vid['target_audience'])
                # Additional mechanism extraction from video structure
                if vid.get('unique_mechanism'):
                    all_mechanisms.append(vid['unique_mechanism'])
                if vid.get('why_others_fail') or vid.get('root_cause_explanation'):
                    all_root_causes.append(vid.get('why_others_fail') or vid.get('root_cause_explanation'))

        # Deduplicate and rank by frequency
        pain_points = self._rank_by_frequency(all_pain_points, max_items=10)
        desires = self._rank_by_frequency(all_desires, max_items=10)
        benefits = self._rank_by_frequency(all_benefits, max_items=10)
        hooks = self._dedupe_similar(all_hooks, max_items=5)
        claims = self._rank_by_frequency(all_claims, max_items=8)
        mechanisms = self._dedupe_similar(all_mechanisms, max_items=3)
        root_causes = self._dedupe_similar(all_root_causes, max_items=3)
        mechanism_solutions = self._dedupe_similar(all_mechanism_solutions, max_items=3)

        # Infer variant name from URL or common themes
        suggested_name = self._infer_variant_name(
            analysis_result.get('display_url', ''),
            benefits,
            pain_points
        )

        # Synthesize target audience
        target_audience = self._synthesize_target_audience(all_target_audiences)

        return {
            'suggested_name': suggested_name,
            'landing_page_url': analysis_result.get('display_url', ''),
            'pain_points': pain_points,
            'desires_goals': desires,
            'benefits': benefits,
            'claims': claims,
            'sample_hooks': hooks,
            'target_audience': target_audience,
            'sample_ctas': list(set(all_ctas))[:3],
            # Unique Mechanism fields (UM/UMP/UMS)
            'mechanism_name': mechanisms[0] if mechanisms else '',
            'mechanism_problem': root_causes[0] if root_causes else '',  # UMP
            'mechanism_solution': mechanism_solutions[0] if mechanism_solutions else '',  # UMS
            # All extracted (for review)
            'all_mechanisms': mechanisms,
            'all_root_causes': root_causes,
            'all_mechanism_solutions': mechanism_solutions,
            # Metadata
            'ad_count': analysis_result.get('total_ads', 0),
            'analyzed_count': analysis_result.get('analyzed_ads', 0),
            'source_ad_ids': analysis_result.get('source_ad_ids', [])
        }

    def _empty_synthesis(self, analysis_result: Dict) -> Dict:
        """Return empty synthesis structure."""
        return {
            'suggested_name': '',
            'landing_page_url': analysis_result.get('display_url', ''),
            'pain_points': [],
            'desires_goals': [],
            'benefits': [],
            'claims': [],
            'sample_hooks': [],
            'target_audience': '',
            'sample_ctas': [],
            # Unique Mechanism fields (UM/UMP/UMS)
            'mechanism_name': '',
            'mechanism_problem': '',
            'mechanism_solution': '',
            'all_mechanisms': [],
            'all_root_causes': [],
            'all_mechanism_solutions': [],
            # Metadata
            'ad_count': analysis_result.get('total_ads', 0),
            'analyzed_count': 0,
            'source_ad_ids': []
        }

    def _rank_by_frequency(
        self,
        items: List[str],
        max_items: int = 10,
        min_count: int = 1
    ) -> List[str]:
        """
        Rank items by frequency, deduplicate similar items.

        Args:
            items: List of strings to rank
            max_items: Maximum items to return
            min_count: Minimum occurrences to include

        Returns:
            List of unique items sorted by frequency
        """
        if not items:
            return []

        # Normalize items (lowercase, strip)
        normalized = [s.strip().lower() for s in items if s and s.strip()]

        # Count frequencies
        counter = Counter(normalized)

        # Filter by min_count and get top items
        ranked = [
            item for item, count in counter.most_common(max_items * 2)
            if count >= min_count
        ]

        # Return with original casing (find first occurrence)
        original_case = {}
        for item in items:
            if item and item.strip():
                key = item.strip().lower()
                if key not in original_case:
                    original_case[key] = item.strip()

        result = [original_case.get(r, r) for r in ranked[:max_items]]
        return result

    def _dedupe_similar(self, items: List[str], max_items: int = 5) -> List[str]:
        """
        Deduplicate similar strings (keep longest/most complete).

        Args:
            items: List of strings to deduplicate
            max_items: Maximum items to return

        Returns:
            List of unique, diverse items
        """
        if not items:
            return []

        # Remove exact duplicates
        unique = list(dict.fromkeys([s.strip() for s in items if s and s.strip()]))

        # Sort by length (prefer longer, more complete hooks)
        unique.sort(key=len, reverse=True)

        # Filter out items that are substrings of others
        result = []
        for item in unique:
            is_substring = False
            item_lower = item.lower()
            for existing in result:
                if item_lower in existing.lower() or existing.lower() in item_lower:
                    is_substring = True
                    break
            if not is_substring:
                result.append(item)
                if len(result) >= max_items:
                    break

        return result

    def _infer_variant_name(
        self,
        url: str,
        benefits: List[str],
        pain_points: List[str]
    ) -> str:
        """
        Infer a suggested variant name from URL and themes.

        Args:
            url: Landing page URL
            benefits: List of benefits
            pain_points: List of pain points

        Returns:
            Suggested variant name
        """
        # Try to extract from URL path
        if url:
            parsed = urlparse(url if url.startswith('http') else f'https://{url}')
            path = parsed.path.strip('/')

            if path:
                # Take last path segment
                segments = [s for s in path.split('/') if s]
                if segments:
                    last = segments[-1]
                    # Clean up common patterns
                    name = last.replace('-', ' ').replace('_', ' ')
                    # Remove common suffixes
                    for suffix in ['lp', 'landing', 'page', 'offer', 'sales']:
                        name = name.replace(suffix, '').strip()
                    if name and len(name) > 2:
                        return name.title()

        # Fall back to first benefit or pain point
        if benefits:
            return benefits[0][:50].title()
        if pain_points:
            return f"{pain_points[0][:30]} Solution".title()

        return "Offer Variant"

    def _synthesize_target_audience(self, audiences: List[str]) -> str:
        """
        Synthesize target audience from multiple descriptions.

        Args:
            audiences: List of target audience descriptions

        Returns:
            Synthesized target audience string
        """
        if not audiences:
            return ""

        # If only one, return it
        if len(audiences) == 1:
            return audiences[0]

        # Find common themes
        # For now, return the longest description as it's likely most complete
        return max(audiences, key=len)

    # ============================================================
    # Convenience Methods
    # ============================================================

    async def analyze_and_synthesize(
        self,
        ad_group: AdGroup,
        max_ads: int = 10,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Analyze an ad group and synthesize messaging in one call.

        Convenience method combining analyze_ad_group() and synthesize_messaging().

        Args:
            ad_group: AdGroup to analyze
            max_ads: Maximum ads to analyze
            progress_callback: Optional progress callback

        Returns:
            Synthesized messaging dict ready for offer variant creation
        """
        analysis_result = await self.analyze_ad_group(
            ad_group,
            max_ads=max_ads,
            progress_callback=progress_callback
        )

        # If resuming, fetch existing analyses and merge with new ones
        already_analyzed_ids = analysis_result.get('already_analyzed_ids', [])
        if already_analyzed_ids:
            existing_analyses = self._fetch_existing_analyses(already_analyzed_ids)
            all_analyses = existing_analyses + analysis_result.get('analyses', [])
            analysis_result['analyses'] = all_analyses
            analysis_result['analyzed_ads'] = len(all_analyses)
            logger.info(f"Merged {len(existing_analyses)} existing + "
                       f"{len(analysis_result.get('analyses', []) or []) - len(existing_analyses)} new analyses")

        synthesis = self.synthesize_messaging(analysis_result)

        # Include raw analyses for transparency
        synthesis['_raw_analyses'] = analysis_result.get('analyses', [])
        synthesis['_resume_info'] = {
            'skipped_ads': analysis_result.get('skipped_ads', 0),
            'new_analyses': analysis_result.get('analyzed_ads', 0) - analysis_result.get('skipped_ads', 0)
        }

        return synthesis

    # ============================================================
    # Meta Ad Grouping (for Meta-only brands)
    # ============================================================

    def group_meta_ads_by_destination(
        self, brand_id: str, min_ads: int = 1, days_back: int = 90
    ) -> List[Dict]:
        """Group Meta ads by destination URL for variant discovery.

        Aggregates per-ad first (DISTINCT meta_ad_ids), then per-group.
        Deduplicates ads appearing in multiple canonical URLs.

        Args:
            brand_id: Brand UUID string
            min_ads: Minimum number of distinct ads per group
            days_back: Date window for performance aggregation

        Returns:
            List of MetaAdGroup-like dicts sorted by total_spend DESC
        """
        from viraltracker.services.url_canonicalizer import canonicalize_url
        from datetime import timedelta

        # 1. Get all destination URLs for brand
        dest_result = self.supabase.table("meta_ad_destinations").select(
            "id, meta_ad_id, destination_url, canonical_url"
        ).eq("brand_id", brand_id).execute()

        if not dest_result.data:
            return []

        # 2. Dedupe: assign each meta_ad_id to its first canonical URL only
        ad_to_canonical = {}  # meta_ad_id -> canonical_url
        for row in dest_result.data:
            ad_id = row.get("meta_ad_id")
            canonical = row.get("canonical_url") or canonicalize_url(row.get("destination_url", ""))
            if ad_id and ad_id not in ad_to_canonical:
                ad_to_canonical[ad_id] = canonical

        # 3. Group by canonical URL
        groups = {}  # canonical_url -> {meta_ad_ids, display_url}
        for row in dest_result.data:
            ad_id = row.get("meta_ad_id")
            canonical = row.get("canonical_url") or canonicalize_url(row.get("destination_url", ""))
            # Only count this ad in this group if it's the ad's assigned group
            if ad_id and ad_to_canonical.get(ad_id) == canonical:
                if canonical not in groups:
                    groups[canonical] = {
                        "canonical_url": canonical,
                        "display_url": row.get("destination_url", ""),
                        "meta_ad_ids": set(),
                    }
                groups[canonical]["meta_ad_ids"].add(ad_id)

        # 4. Get performance data (per-ad aggregation)
        all_ad_ids = list(ad_to_canonical.keys())
        ad_performance = {}  # meta_ad_id -> {spend, impressions, purchases, purchase_value}

        for i in range(0, len(all_ad_ids), 50):
            batch = all_ad_ids[i:i + 50]
            perf_result = self.supabase.table("meta_ads_performance").select(
                "meta_ad_id, spend, impressions, purchases, purchase_roas"
            ).eq("brand_id", brand_id).in_("meta_ad_id", batch).gte(
                "date", (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            ).execute()

            for row in (perf_result.data or []):
                ad_id = row["meta_ad_id"]
                if ad_id not in ad_performance:
                    ad_performance[ad_id] = {"spend": 0, "impressions": 0, "purchases": 0, "purchase_value": 0}
                ad_performance[ad_id]["spend"] += float(row.get("spend") or 0)
                ad_performance[ad_id]["impressions"] += int(row.get("impressions") or 0)
                ad_performance[ad_id]["purchases"] += int(row.get("purchases") or 0)

        # 5. Get sample ad copy
        ad_copy = {}
        for i in range(0, len(all_ad_ids), 50):
            batch = all_ad_ids[i:i + 50]
            copy_result = self.supabase.table("meta_ads").select(
                "meta_ad_id, ad_copy"
            ).in_("meta_ad_id", batch).execute()
            for row in (copy_result.data or []):
                if row.get("ad_copy"):
                    ad_copy[row["meta_ad_id"]] = row["ad_copy"]

        # 6. Check existing analyses
        analyzed_ads = set()
        for i in range(0, len(all_ad_ids), 50):
            batch = all_ad_ids[i:i + 50]
            analysis_result = self.supabase.table("brand_ad_analysis").select(
                "meta_ad_id"
            ).eq("brand_id", brand_id).in_("meta_ad_id", batch).execute()
            for row in (analysis_result.data or []):
                if row.get("meta_ad_id"):
                    analyzed_ads.add(row["meta_ad_id"])

        # 7. Build result
        result = []
        for canonical, group in groups.items():
            ad_ids = list(group["meta_ad_ids"])
            ad_count = len(ad_ids)
            if ad_count < min_ads:
                continue

            total_spend = sum(ad_performance.get(aid, {}).get("spend", 0) for aid in ad_ids)
            total_impressions = sum(ad_performance.get(aid, {}).get("impressions", 0) for aid in ad_ids)
            total_purchases = sum(ad_performance.get(aid, {}).get("purchases", 0) for aid in ad_ids)
            total_purchase_value = sum(ad_performance.get(aid, {}).get("purchase_value", 0) for aid in ad_ids)

            sample_copy = None
            for aid in ad_ids:
                if aid in ad_copy:
                    sample_copy = ad_copy[aid]
                    break

            analyzed_count = len(set(ad_ids) & analyzed_ads)

            result.append({
                "canonical_url": canonical,
                "display_url": group["display_url"],
                "ad_count": ad_count,
                "meta_ad_ids": ad_ids[:20],  # Limit for payload size
                "sample_ad_copy": sample_copy[:300] if sample_copy else None,
                "total_spend": round(total_spend, 2),
                "total_impressions": total_impressions,
                "total_purchases": total_purchases,
                "avg_roas": round(total_purchase_value / total_spend, 2) if total_spend > 0 else None,
                "analyzed_count": analyzed_count,
            })

        # Sort by total_spend DESC
        result.sort(key=lambda x: x["total_spend"], reverse=True)
        return result

    def fetch_meta_analyses_for_group(self, brand_id: str, meta_ad_ids: List[str]) -> Dict:
        """Fetch existing brand_ad_analysis records for a group of Meta ads.

        Returns a structure compatible with synthesize_messaging().
        """
        analyses = []
        for i in range(0, len(meta_ad_ids), 50):
            batch = meta_ad_ids[i:i + 50]
            result = self.supabase.table("brand_ad_analysis").select("*").eq(
                "brand_id", brand_id
            ).in_("meta_ad_id", batch).execute()
            analyses.extend(result.data or [])

        # Restructure into synthesize_messaging format
        formatted_analyses = []
        for a in analyses:
            raw = a.get("raw_response", {})
            formatted = {}
            if a.get("analysis_type") == "copy_analysis":
                formatted["copy_analysis"] = raw
            elif a.get("analysis_type") == "image_vision":
                formatted["image_analysis"] = raw
            elif a.get("analysis_type") == "video_vision":
                formatted["video_analysis"] = raw
            else:
                formatted["copy_analysis"] = raw
            formatted_analyses.append(formatted)

        return {
            "analyses": formatted_analyses,
            "analyzed_ads": len(formatted_analyses),
            "ad_count": len(meta_ad_ids),
            "source_ad_ids": meta_ad_ids[:20],
        }

    def synthesize_from_raw_copy(self, ad_copies: List[str], landing_page_url: str) -> Dict:
        """Lightweight extraction from raw ad copy text.

        Used when no full analysis exists yet. Returns same shape as
        synthesize_messaging() but with basic extraction.

        Args:
            ad_copies: List of raw ad copy strings
            landing_page_url: The destination URL

        Returns:
            Synthesis dict compatible with the shared form
        """
        # Basic pattern extraction from raw text
        all_text = "\n---\n".join(c for c in ad_copies if c)
        if not all_text:
            return self._empty_raw_synthesis(landing_page_url)

        # Extract potential hooks (first sentence patterns)
        hooks = []
        for copy in ad_copies[:10]:
            if copy:
                first_line = copy.strip().split("\n")[0].strip()
                if first_line and len(first_line) < 150:
                    hooks.append(first_line)

        # Generate a suggested name from URL
        url_path = landing_page_url.rstrip("/").split("/")[-1] if landing_page_url else ""
        name_from_url = url_path.replace("-", " ").replace("_", " ").title() if url_path else "Meta Ad Variant"

        return {
            "suggested_name": name_from_url,
            "landing_page_url": landing_page_url,
            "pain_points": [],
            "desires_goals": [],
            "benefits": [],
            "target_audience": "",
            "mechanism_name": "",
            "mechanism_problem": "",
            "mechanism_solution": "",
            "sample_hooks": hooks[:5],
            "analyzed_count": len(ad_copies),
            "source_ad_ids": [],
            "_needs_full_analysis": True,
        }

    def _empty_raw_synthesis(self, landing_page_url: str) -> Dict:
        """Return empty synthesis structure."""
        return {
            "suggested_name": "Unnamed Variant",
            "landing_page_url": landing_page_url,
            "pain_points": [],
            "desires_goals": [],
            "benefits": [],
            "target_audience": "",
            "mechanism_name": "",
            "mechanism_problem": "",
            "mechanism_solution": "",
            "sample_hooks": [],
            "analyzed_count": 0,
            "source_ad_ids": [],
            "_needs_full_analysis": True,
        }
