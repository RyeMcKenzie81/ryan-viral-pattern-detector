"""
Content Exporter

Export generated content in multiple formats:
- Markdown (for review/publishing)
- JSON (for programmatic use)
- CSV (for analysis)
- Platform-specific (Twitter, Medium, WordPress, etc.)

Usage:
    exporter = ContentExporter()
    exporter.export_to_markdown(content, output_path)
"""

import logging
from typing import List
import json
import csv
from pathlib import Path

from .content_generator import GeneratedContent


logger = logging.getLogger(__name__)


class ContentExporter:
    """
    Export generated content in various formats
    """

    @staticmethod
    def _get_tweet_url(tweet_id: str) -> str:
        """
        Construct Twitter/X URL from tweet ID

        Args:
            tweet_id: Tweet ID

        Returns:
            Full URL to tweet
        """
        if not tweet_id:
            return None
        return f"https://twitter.com/i/web/status/{tweet_id}"

    def export_to_markdown(self, content_list: List[GeneratedContent], output_path: str) -> None:
        """
        Export content to markdown file

        Args:
            content_list: List of GeneratedContent objects
            output_path: Output file path
        """
        lines = []
        lines.append("# Generated Content Export\n")
        lines.append(f"**Total Pieces**: {len(content_list)}\n")
        lines.append(f"**Generated**: {content_list[0].created_at.strftime('%Y-%m-%d %H:%M:%S') if content_list else 'N/A'}\n")
        lines.append("\n---\n")

        for i, content in enumerate(content_list, 1):
            lines.append(f"\n## {i}. {content.content_title}\n")
            lines.append(f"- **Type**: {content.content_type}\n")
            lines.append(f"- **Hook**: {content.hook_type}\n")
            lines.append(f"- **Emotional Trigger**: {content.emotional_trigger}\n")
            lines.append(f"- **Status**: {content.status}\n")
            lines.append(f"- **Cost**: ${content.api_cost_usd:.6f}\n")
            lines.append(f"- **ID**: `{content.id}`\n")

            # Add source tweet URL
            tweet_url = self._get_tweet_url(content.source_tweet_id)
            if tweet_url:
                lines.append(f"- **Source Tweet**: {tweet_url}\n")

            if content.source_tweet_text:
                lines.append(f"\n### Source Tweet\n")
                lines.append(f"> {content.source_tweet_text}\n")

            if content.hook_explanation:
                lines.append(f"\n### Why It Works\n")
                lines.append(f"{content.hook_explanation}\n")

            lines.append(f"\n### Content\n")

            if content.content_type == 'thread':
                lines.append(self._format_thread_markdown(content))
            elif content.content_type == 'blog':
                lines.append(self._format_blog_markdown(content))
            else:
                lines.append(f"\n{content.content_body}\n")

            lines.append("\n---\n")

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"Exported {len(content_list)} items to markdown: {output_path}")

    def export_to_json(self, content_list: List[GeneratedContent], output_path: str) -> None:
        """
        Export content to JSON file

        Args:
            content_list: List of GeneratedContent objects
            output_path: Output file path
        """
        data = {
            'total': len(content_list),
            'generated_at': content_list[0].created_at.isoformat() if content_list else None,
            'content': []
        }

        for content in content_list:
            data['content'].append({
                'id': content.id,
                'project_id': content.project_id,
                'type': content.content_type,
                'title': content.content_title,
                'body': content.content_body,
                'metadata': content.content_metadata,
                'hook': {
                    'type': content.hook_type,
                    'emotional_trigger': content.emotional_trigger,
                    'pattern': content.content_pattern,
                    'explanation': content.hook_explanation,
                    'adaptation_notes': content.adaptation_notes
                },
                'source_tweet_id': content.source_tweet_id,
                'source_tweet_url': self._get_tweet_url(content.source_tweet_id),
                'status': content.status,
                'cost_usd': float(content.api_cost_usd),
                'model': content.model_used,
                'created_at': content.created_at.isoformat()
            })

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported {len(content_list)} items to JSON: {output_path}")

    def export_to_csv(self, content_list: List[GeneratedContent], output_path: str) -> None:
        """
        Export content to CSV file

        Args:
            content_list: List of GeneratedContent objects
            output_path: Output file path
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                'id', 'project_id', 'content_type', 'title',
                'hook_type', 'emotional_trigger', 'content_pattern',
                'status', 'cost_usd', 'model', 'created_at',
                'word_count', 'source_tweet_id', 'source_tweet_url'
            ])

            # Rows
            for content in content_list:
                word_count = len(content.content_body.split()) if content.content_body else 0
                writer.writerow([
                    content.id,
                    content.project_id,
                    content.content_type,
                    content.content_title,
                    content.hook_type,
                    content.emotional_trigger,
                    content.content_pattern,
                    content.status,
                    content.api_cost_usd,
                    content.model_used,
                    content.created_at.isoformat(),
                    word_count,
                    content.source_tweet_id or '',
                    self._get_tweet_url(content.source_tweet_id) or ''
                ])

        logger.info(f"Exported {len(content_list)} items to CSV: {output_path}")

    def export_thread_for_twitter(self, content: GeneratedContent, output_path: str) -> None:
        """
        Export thread in Twitter-ready format

        Args:
            content: GeneratedContent with thread
            output_path: Output file path
        """
        if content.content_type != 'thread':
            raise ValueError("Content must be of type 'thread'")

        tweets = content.content_metadata.get('tweets', [])

        lines = [
            "=== TWITTER THREAD ===",
            f"Title: {content.content_title}",
            f"Hook: {content.hook_type} / {content.emotional_trigger}",
            ""
        ]

        # Add source tweet URL
        tweet_url = self._get_tweet_url(content.source_tweet_id)
        if tweet_url:
            lines.append(f"Source: {tweet_url}")
            lines.append("")

        lines.extend([
            "Copy and paste each tweet below:",
            "=" * 60,
            ""
        ])

        for tweet in tweets:
            text = tweet.get('text', '')
            number = tweet.get('number', 0)
            char_count = len(text)

            lines.append(f"Tweet {number}/{len(tweets)} ({char_count} chars):")
            lines.append(text)
            lines.append("")

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"Exported thread for Twitter: {output_path}")

    def export_thread_as_longform(self, content: GeneratedContent, output_path: str) -> None:
        """
        Export thread as single long-form post for LinkedIn/Instagram

        Args:
            content: GeneratedContent with thread
            output_path: Output file path
        """
        if content.content_type != 'thread':
            raise ValueError("Content must be of type 'thread'")

        tweets = content.content_metadata.get('tweets', [])

        # Create header
        lines = [
            "=== LONG-FORM POST (LinkedIn/Instagram/Single Post) ===",
            f"Title: {content.content_title}",
            f"Hook: {content.hook_type} / {content.emotional_trigger}",
            ""
        ]

        # Add source tweet URL
        tweet_url = self._get_tweet_url(content.source_tweet_id)
        if tweet_url:
            lines.append(f"Source: {tweet_url}")
            lines.append("")

        lines.extend([
            "Copy and paste below:",
            "=" * 60,
            ""
        ])

        # Combine all tweets into paragraphs
        paragraphs = []
        for tweet in tweets:
            text = tweet.get('text', '').strip()
            paragraphs.append(text)

        longform = "\n\n".join(paragraphs)
        lines.append(longform)

        # Add character count
        char_count = len(longform)
        lines.append("")
        lines.append("=" * 60)
        lines.append(f"Total characters: {char_count}")
        lines.append(f"LinkedIn limit: 3,000 chars ({3000 - char_count} remaining)")
        lines.append(f"Instagram limit: 2,200 chars ({2200 - char_count} remaining)")

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"Exported thread as long-form post: {output_path}")

    def export_blog_for_medium(self, content: GeneratedContent, output_path: str) -> None:
        """
        Export blog in Medium-ready markdown format

        Args:
            content: GeneratedContent with blog
            output_path: Output file path
        """
        if content.content_type != 'blog':
            raise ValueError("Content must be of type 'blog'")

        metadata = content.content_metadata
        lines = [
            f"# {content.content_title}",
            ""
        ]

        if metadata.get('subtitle'):
            lines.append(f"*{metadata.get('subtitle')}*")
            lines.append("")

        lines.append(metadata.get('content', content.content_body))

        # Add source tweet URL as footer
        tweet_url = self._get_tweet_url(content.source_tweet_id)
        if tweet_url:
            lines.append("")
            lines.append("---")
            lines.append("")
            lines.append(f"*Inspired by [this viral tweet]({tweet_url})*")

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"Exported blog for Medium: {output_path}")

    def _format_thread_markdown(self, content: GeneratedContent) -> str:
        """Format thread as markdown"""
        tweets = content.content_metadata.get('tweets', [])

        lines = []
        for tweet in tweets:
            number = tweet.get('number', 0)
            text = tweet.get('text', '')
            char_count = tweet.get('char_count', len(text))

            lines.append(f"\n**Tweet {number}/{len(tweets)}** ({char_count} chars):")
            lines.append(f"> {text}\n")

        # Add metadata
        if content.content_metadata.get('key_insights'):
            lines.append("\n### Key Insights\n")
            for insight in content.content_metadata['key_insights']:
                lines.append(f"- {insight}")

        return '\n'.join(lines)

    def _format_blog_markdown(self, content: GeneratedContent) -> str:
        """Format blog as markdown"""
        metadata = content.content_metadata

        lines = []

        if metadata.get('seo_description'):
            lines.append(f"*{metadata.get('seo_description')}*\n")

        lines.append(metadata.get('content', content.content_body))

        # Add metadata
        lines.append("\n---\n")
        lines.append(f"**Word Count**: {metadata.get('word_count', 0)}")
        lines.append(f"**Reading Time**: {metadata.get('reading_time_minutes', 0)} minutes")

        if metadata.get('key_takeaways'):
            lines.append("\n### Key Takeaways\n")
            for takeaway in metadata['key_takeaways']:
                lines.append(f"- {takeaway}")

        return '\n'.join(lines)
