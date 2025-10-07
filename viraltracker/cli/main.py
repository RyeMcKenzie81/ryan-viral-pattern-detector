"""
Main CLI entry point for ViralTracker
"""

import click
from .import_urls import import_url_group
from .brand import brand_group
from .product import product_group
from .project import project_group
from .scrape import scrape_command
from .process import process_group
from .analyze import analyze_group
from .script import script_group


@click.group()
@click.version_option(version='0.1.0')
def cli():
    """
    ViralTracker - Multi-brand viral content analysis system

    Analyze viral content across Instagram, TikTok, and YouTube Shorts.
    Compare your content against competitors and track patterns.
    """
    pass


# Register command groups
cli.add_command(brand_group)
cli.add_command(product_group)
cli.add_command(project_group)
cli.add_command(import_url_group)
cli.add_command(scrape_command)
cli.add_command(process_group)
cli.add_command(analyze_group)
cli.add_command(script_group)


if __name__ == '__main__':
    cli()
