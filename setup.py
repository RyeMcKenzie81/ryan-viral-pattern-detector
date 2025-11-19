"""
Setup configuration for viraltracker package.
"""

from setuptools import setup, find_packages

setup(
    name="viraltracker",
    version="0.1.0",
    description="Viral content analysis and tracking system",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        # Dependencies are managed in requirements.txt
        # Install with: pip install -e .
    ],
)
