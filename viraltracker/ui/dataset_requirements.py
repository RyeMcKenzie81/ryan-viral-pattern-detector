"""
Dataset Requirements Registry - Maps pages to their required datasets.

Each page key maps to a list of dataset requirements. The freshness banner
uses this to determine which warnings to show on each page.

Usage:
    from viraltracker.ui.dataset_requirements import DATASET_REQUIREMENTS

    requirements = DATASET_REQUIREMENTS.get("ad_performance", [])
"""

DATASET_REQUIREMENTS = {
    "ad_performance": [
        {
            "dataset_key": "meta_ads_performance",
            "max_age_hours": 24,
            "label": "Ad Performance Data",
            "fix_action": "Queue a Meta Sync job for the last 30 days",
            "fix_job_type": "meta_sync",
        },
    ],
    "hook_analysis": [
        {
            "dataset_key": "ad_classifications",
            "max_age_hours": 48,
            "label": "Ad Classifications",
            "fix_action": "Queue an Ad Classification job",
            "fix_job_type": "ad_classification",
        },
    ],
    "template_queue": [
        {
            "dataset_key": "templates_scraped",
            "max_age_hours": 168,
            "label": "Scraped Templates",
            "fix_action": "Queue a Template Scrape job",
            "fix_job_type": "template_scrape",
        },
    ],
    "template_evaluation": [
        {
            "dataset_key": "templates_evaluated",
            "max_age_hours": 168,
            "label": "Template Evaluations",
            "fix_action": "Queue a Template Approval job",
            "fix_job_type": "template_approval",
        },
    ],
    "congruence_insights": [
        {
            "dataset_key": "ad_classifications",
            "max_age_hours": 48,
            "label": "Ad Classifications",
            "fix_action": "Queue an Ad Classification job",
            "fix_job_type": "ad_classification",
        },
        {
            "dataset_key": "landing_pages",
            "max_age_hours": 168,
            "label": "Landing Page Data",
            "fix_action": "Run Brand Research to refresh landing pages",
            "fix_job_type": None,
        },
    ],
}
