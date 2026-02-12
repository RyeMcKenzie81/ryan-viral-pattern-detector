"""
Tool Readiness Requirements Registry.

Single source of truth for what each tool needs. Any scope change to tool
prerequisites (new requirements, removed checks, threshold tweaks) MUST go
through this registry.

Requirement types:
- hard: Tool is BLOCKED if any hard requirement is unmet
- soft: Tool works but in degraded mode if unmet
- freshness: Uses DatasetFreshnessService to check dataset age

Check types (evaluated by ToolReadinessService):
- "count_gt_zero": table has >= 1 row matching filters
- "count_via_products": join through products table for tables without brand_id
- "count_any_of": check multiple tables, True if any has rows
- "field_not_null": a specific field on a record is not null/empty
- "competitors_have_field": count competitors with non-null field vs total
- "dataset_fresh": uses DatasetFreshnessService.check_is_fresh()

Group types:
- any_of_groups: List of groups where each group passes if ANY sub-requirement
  is met. Each group has:
  - "group_key": unique key for the group result
  - "group_label": display label
  - "group_type": "hard" or "soft" — determines BLOCKED vs PARTIAL when unmet
  - "requirements": list of standard requirement dicts

Dependency tracking:
- unlocks: List of tool_keys that this tool enables when it becomes ready.
  Used to show "Enables: X, Y, Z" badges on blocked/partial tools, helping
  users prioritize which prerequisites to satisfy first.
"""

TOOL_REQUIREMENTS = {
    # ---------------------------------------------------------------
    # Brands section
    # ---------------------------------------------------------------
    "brand_research": {
        "label": "Brand Research",
        "icon": "🔬",
        "page_link": "pages/05_🔬_Brand_Research.py",
        "feature_key": "brand_research",
        "hard": [
            {
                "key": "has_products",
                "label": "Products configured",
                "check": "count_gt_zero",
                "table": "products",
                "filter": {"brand_id": "{brand_id}"},
                "fix_action": "Add at least one product",
                "fix_page_link": "pages/02_🏢_Brand_Manager.py",
            },
        ],
        "soft": [],
        "any_of_groups": [{
            "group_key": "has_data_source",
            "group_label": "Ad data source configured",
            "group_type": "soft",
            "requirements": [
                {"key": "has_ad_library_url", "label": "Ad Library URL", "check": "field_not_null",
                 "table": "brands", "field": "ad_library_url", "filter": {"id": "{brand_id}"},
                 "fix_action": "Set Ad Library URL in Brand Manager", "fix_page_link": "pages/02_🏢_Brand_Manager.py"},
                {"key": "has_ad_account", "label": "Meta ad account linked", "check": "count_gt_zero",
                 "table": "brand_ad_accounts", "filter": {"brand_id": "{brand_id}"},
                 "fix_action": "Link a Meta ad account", "fix_page_link": "pages/02_🏢_Brand_Manager.py"},
            ],
        }],
        "unlocks": ["url_mapping", "hook_analysis", "congruence_insights", "personas", "research_insights", "landing_page_analyzer"],
        "freshness": [],
    },
    "ad_performance": {
        "label": "Ad Performance",
        "icon": "📈",
        "page_link": "pages/30_📈_Ad_Performance.py",
        "feature_key": "ad_performance",
        "hard": [
            {
                "key": "has_ad_account",
                "label": "Ad account linked",
                "check": "count_gt_zero",
                "table": "brand_ad_accounts",
                "filter": {"brand_id": "{brand_id}"},
                "fix_action": "Link a Meta ad account",
                "fix_page_link": "pages/02_🏢_Brand_Manager.py",
            },
        ],
        "soft": [],
        "any_of_groups": [{
            "group_key": "has_ad_data",
            "group_label": "Ad data available",
            "group_type": "soft",
            "requirements": [
                {"key": "has_scraped_ads", "label": "Ads scraped (Ad Library)", "check": "count_gt_zero",
                 "table": "brand_facebook_ads", "filter": {"brand_id": "{brand_id}"},
                 "fix_action": "Scrape ads from Brand Research", "fix_page_link": "pages/05_🔬_Brand_Research.py"},
                {"key": "has_meta_ads", "label": "Meta API ads synced", "check": "count_gt_zero",
                 "table": "meta_ads_performance", "filter": {"brand_id": "{brand_id}"},
                 "fix_action": "Sync ads via Meta Ad Account", "fix_page_link": "pages/30_📈_Ad_Performance.py"},
            ],
        }],
        "unlocks": ["hook_analysis", "congruence_insights", "url_mapping"],
        "freshness": [
            {
                "key": "meta_ads_performance",
                "label": "Ad Performance Data",
                "dataset_key": "meta_ads_performance",
                "max_age_hours": 24,
                "fix_action": "Queue a Meta Sync job",
                "fix_job_type": "meta_sync",
            },
        ],
    },
    "url_mapping": {
        "label": "URL Mapping",
        "icon": "🔗",
        "page_link": "pages/04_🔗_URL_Mapping.py",
        "feature_key": "url_mapping",
        "hard": [
            {
                "key": "has_products",
                "label": "Products configured",
                "check": "count_gt_zero",
                "table": "products",
                "filter": {"brand_id": "{brand_id}"},
                "fix_action": "Add products in Brand Manager",
                "fix_page_link": "pages/02_🏢_Brand_Manager.py",
            },
        ],
        "any_of_groups": [{
            "group_key": "has_ad_urls",
            "group_label": "Ad URL data available",
            "group_type": "hard",
            "requirements": [
                {"key": "has_scraped_ads", "label": "Ads scraped (Ad Library)", "check": "count_gt_zero",
                 "table": "brand_facebook_ads", "filter": {"brand_id": "{brand_id}"},
                 "fix_action": "Scrape ads from Brand Research", "fix_page_link": "pages/05_🔬_Brand_Research.py"},
                {"key": "has_meta_destinations", "label": "Meta destination URLs fetched", "check": "count_gt_zero",
                 "table": "meta_ad_destinations", "filter": {"brand_id": "{brand_id}"},
                 "fix_action": "Run Meta Sync to fetch destination URLs", "fix_page_link": "pages/30_📈_Ad_Performance.py"},
            ],
        }],
        "unlocks": [],
        "soft": [
            {
                "key": "has_product_urls",
                "label": "Product URLs configured",
                "check": "count_via_products",
                "table": "product_urls",
                "join_table": "products",
                "join_key": "product_id",
                "fix_action": "Add product URLs",
                "fix_page_link": "pages/04_🔗_URL_Mapping.py",
            },
        ],
        "freshness": [],
    },
    "competitor_research": {
        "label": "Competitor Research",
        "icon": "🔍",
        "page_link": "pages/12_🔍_Competitor_Research.py",
        "feature_key": "competitor_research",
        "applicable_when": {
            "check": "count_gt_zero",
            "table": "competitors",
            "filter": {"brand_id": "{brand_id}"},
            "reason": "No competitors configured for this brand",
        },
        "hard": [],
        "soft": [
            {
                "key": "competitor_ad_library_urls",
                "label": "Competitor Ad Library URLs",
                "check": "competitors_have_field",
                "field": "ad_library_url",
                "fix_action": "Set Ad Library URLs on competitors",
                "fix_page_link": "pages/11_🎯_Competitors.py",
            },
        ],
        "unlocks": ["competitive_analysis"],
        "freshness": [],
    },
    "ad_creator": {
        "label": "Ad Creator",
        "icon": "🎨",
        "page_link": "pages/21_🎨_Ad_Creator.py",
        "feature_key": "ad_creator",
        "hard": [
            {
                "key": "has_products",
                "label": "Products configured",
                "check": "count_gt_zero",
                "table": "products",
                "filter": {"brand_id": "{brand_id}"},
                "fix_action": "Add products in Brand Manager",
                "fix_page_link": "pages/02_🏢_Brand_Manager.py",
            },
        ],
        "soft": [
            {
                "key": "has_offer_variants",
                "label": "Offer variants configured",
                "check": "count_via_products",
                "table": "product_offer_variants",
                "join_table": "products",
                "join_key": "product_id",
                "fix_action": "Add offer variants in Brand Manager",
                "fix_page_link": "pages/02_🏢_Brand_Manager.py",
            },
            {
                "key": "has_personas",
                "label": "Personas generated",
                "check": "count_gt_zero",
                "table": "personas_4d",
                "filter": {"brand_id": "{brand_id}"},
                "fix_action": "Generate personas",
                "fix_page_link": "pages/03_👤_Personas.py",
            },
            {
                "key": "has_templates",
                "label": "Templates available",
                "check": "count_any_of",
                "tables": ["ad_templates", "scraped_templates"],
                "fix_action": "Set up template scraping in Pipeline Manager",
                "fix_page_link": "pages/62_🔧_Pipeline_Manager.py",
            },
            {
                "key": "has_angles",
                "label": "Belief angles available",
                "check": "count_gt_zero",
                "table": "angle_candidates",
                "filter": {"brand_id": "{brand_id}"},
                "fix_action": "Discover angles in Research Insights",
                "fix_page_link": "pages/32_💡_Research_Insights.py",
            },
        ],
        "unlocks": [],
        "freshness": [],
    },

    # ---------------------------------------------------------------
    # Freshness-dependent tools
    # ---------------------------------------------------------------
    "hook_analysis": {
        "label": "Hook Analysis",
        "icon": "🎣",
        "page_link": "pages/35_🎣_Hook_Analysis.py",
        "feature_key": "hook_analysis",
        "hard": [],
        "any_of_groups": [{
            "group_key": "has_ad_data",
            "group_label": "Ad data available",
            "group_type": "hard",
            "requirements": [
                {"key": "has_scraped_ads", "label": "Ads scraped (Ad Library)", "check": "count_gt_zero",
                 "table": "brand_facebook_ads", "filter": {"brand_id": "{brand_id}"},
                 "fix_action": "Scrape ads from Brand Research", "fix_page_link": "pages/05_🔬_Brand_Research.py"},
                {"key": "has_meta_ads", "label": "Meta API ads synced", "check": "count_gt_zero",
                 "table": "meta_ads_performance", "filter": {"brand_id": "{brand_id}"},
                 "fix_action": "Sync ads via Meta Ad Account", "fix_page_link": "pages/30_📈_Ad_Performance.py"},
            ],
        }],
        "unlocks": [],
        "soft": [],
        "freshness": [
            {
                "key": "ad_classifications",
                "label": "Ad Classifications",
                "dataset_key": "ad_classifications",
                "max_age_hours": 48,
                "fix_action": "Queue an Ad Classification job",
                "fix_job_type": "ad_classification",
            },
        ],
    },
    "congruence_insights": {
        "label": "Congruence Insights",
        "icon": "🔗",
        "page_link": "pages/34_🔗_Congruence_Insights.py",
        "feature_key": "congruence_insights",
        "hard": [],
        "any_of_groups": [{
            "group_key": "has_ad_data",
            "group_label": "Ad data available",
            "group_type": "hard",
            "requirements": [
                {"key": "has_scraped_ads", "label": "Ads scraped (Ad Library)", "check": "count_gt_zero",
                 "table": "brand_facebook_ads", "filter": {"brand_id": "{brand_id}"},
                 "fix_action": "Scrape ads from Brand Research", "fix_page_link": "pages/05_🔬_Brand_Research.py"},
                {"key": "has_meta_ads", "label": "Meta API ads synced", "check": "count_gt_zero",
                 "table": "meta_ads_performance", "filter": {"brand_id": "{brand_id}"},
                 "fix_action": "Sync ads via Meta Ad Account", "fix_page_link": "pages/30_📈_Ad_Performance.py"},
            ],
        }],
        "unlocks": [],
        "soft": [],
        "freshness": [
            {
                "key": "ad_classifications",
                "label": "Ad Classifications",
                "dataset_key": "ad_classifications",
                "max_age_hours": 48,
                "fix_action": "Queue an Ad Classification job",
                "fix_job_type": "ad_classification",
            },
            {
                "key": "landing_pages",
                "label": "Landing Page Data",
                "dataset_key": "landing_pages",
                "max_age_hours": 168,
                "fix_action": "Run Brand Research to refresh landing pages",
            },
        ],
    },
    "landing_page_analyzer": {
        "label": "Landing Page Analyzer",
        "icon": "🏗️",
        "page_link": "pages/33_🏗️_Landing_Page_Analyzer.py",
        "feature_key": "landing_page_analyzer",
        "hard": [],
        "soft": [
            {
                "key": "has_landing_pages",
                "label": "Landing pages collected",
                "check": "count_gt_zero",
                "table": "brand_landing_pages",
                "filter": {"brand_id": "{brand_id}"},
                "fix_action": "Scrape landing pages from Brand Research",
                "fix_page_link": "pages/05_🔬_Brand_Research.py",
            },
        ],
        "unlocks": [],
        "freshness": [],
    },

    # ---------------------------------------------------------------
    # Remaining tools
    # ---------------------------------------------------------------
    "personas": {
        "label": "Personas",
        "icon": "👤",
        "page_link": "pages/03_👤_Personas.py",
        "feature_key": "personas",
        "hard": [
            {
                "key": "has_products",
                "label": "Products configured",
                "check": "count_gt_zero",
                "table": "products",
                "filter": {"brand_id": "{brand_id}"},
                "fix_action": "Add products in Brand Manager",
                "fix_page_link": "pages/02_🏢_Brand_Manager.py",
            },
        ],
        "soft": [
            {
                "key": "has_amazon_reviews",
                "label": "Amazon reviews collected",
                "check": "count_gt_zero",
                "table": "amazon_reviews",
                "filter": {"brand_id": "{brand_id}"},
                "fix_action": "Configure ASINs and scrape Amazon",
                "fix_page_link": "pages/02_🏢_Brand_Manager.py",
            },
        ],
        "any_of_groups": [{
            "group_key": "has_ad_data",
            "group_label": "Ad data available (for AI personas)",
            "group_type": "soft",
            "requirements": [
                {"key": "has_brand_ads", "label": "Brand ads scraped (Ad Library)", "check": "count_gt_zero",
                 "table": "brand_facebook_ads", "filter": {"brand_id": "{brand_id}"},
                 "fix_action": "Scrape ads from Brand Research", "fix_page_link": "pages/05_🔬_Brand_Research.py"},
                {"key": "has_meta_ads", "label": "Meta API ads synced", "check": "count_gt_zero",
                 "table": "meta_ads_performance", "filter": {"brand_id": "{brand_id}"},
                 "fix_action": "Sync ads via Meta Ad Account", "fix_page_link": "pages/30_📈_Ad_Performance.py"},
            ],
        }],
        "unlocks": ["ad_creator", "competitive_analysis"],
        "freshness": [],
    },
    "research_insights": {
        "label": "Research Insights",
        "icon": "💡",
        "page_link": "pages/32_💡_Research_Insights.py",
        "feature_key": "research_insights",
        "hard": [
            {
                "key": "has_products",
                "label": "Products configured",
                "check": "count_gt_zero",
                "table": "products",
                "filter": {"brand_id": "{brand_id}"},
                "fix_action": "Add products in Brand Manager",
                "fix_page_link": "pages/02_🏢_Brand_Manager.py",
            },
        ],
        "soft": [
            {
                "key": "has_candidates",
                "label": "Angle candidates extracted",
                "check": "count_gt_zero",
                "table": "angle_candidates",
                "filter": {"brand_id": "{brand_id}"},
                "fix_action": "Extract candidates from research sources",
                "fix_page_link": "pages/32_💡_Research_Insights.py",
            },
        ],
        "unlocks": ["ad_planning", "ad_creator"],
        "freshness": [],
    },
    "ad_planning": {
        "label": "Ad Planning",
        "icon": "📋",
        "page_link": "pages/25_📋_Ad_Planning.py",
        "feature_key": "ad_planning",
        "hard": [
            {
                "key": "has_products",
                "label": "Products configured",
                "check": "count_gt_zero",
                "table": "products",
                "filter": {"brand_id": "{brand_id}"},
                "fix_action": "Add products in Brand Manager",
                "fix_page_link": "pages/02_🏢_Brand_Manager.py",
            },
        ],
        "soft": [
            {
                "key": "has_angles",
                "label": "Belief angles available",
                "check": "count_gt_zero",
                "table": "angle_candidates",
                "filter": {"brand_id": "{brand_id}"},
                "fix_action": "Discover angles in Research Insights",
                "fix_page_link": "pages/32_💡_Research_Insights.py",
            },
            {
                "key": "has_templates",
                "label": "Templates available",
                "check": "count_any_of",
                "tables": ["ad_templates", "scraped_templates"],
                "fix_action": "Set up template scraping in Pipeline Manager",
                "fix_page_link": "pages/62_🔧_Pipeline_Manager.py",
            },
        ],
        "unlocks": ["ad_creator"],
        "freshness": [],
    },
    "template_queue": {
        "label": "Template Queue",
        "icon": "📋",
        "page_link": "pages/28_📋_Template_Queue.py",
        "feature_key": "template_queue",
        "hard": [],
        "soft": [],
        "unlocks": ["template_evaluation", "ad_creator", "ad_planning"],
        "freshness": [
            {
                "key": "templates_scraped",
                "label": "Scraped Templates",
                "dataset_key": "templates_scraped",
                "max_age_hours": 168,
                "fix_action": "Set up template scraping in Pipeline Manager",
                "fix_page_link": "pages/62_🔧_Pipeline_Manager.py",
            },
        ],
    },
    "template_evaluation": {
        "label": "Template Evaluation",
        "icon": "🔍",
        "page_link": "pages/29_🔍_Template_Evaluation.py",
        "feature_key": "template_evaluation",
        "hard": [],
        "soft": [],
        "unlocks": ["ad_creator"],
        "freshness": [
            {
                "key": "templates_evaluated",
                "label": "Template Evaluations",
                "dataset_key": "templates_evaluated",
                "max_age_hours": 168,
                "fix_action": "Queue a Template Approval job",
                "fix_job_type": "template_approval",
                "fix_page_link": "pages/62_🔧_Pipeline_Manager.py",
            },
        ],
    },
    "competitive_analysis": {
        "label": "Competitive Analysis",
        "icon": "📊",
        "page_link": "pages/13_📊_Competitive_Analysis.py",
        "feature_key": "competitive_analysis",
        "applicable_when": {
            "check": "count_gt_zero",
            "table": "competitors",
            "filter": {"brand_id": "{brand_id}"},
            "reason": "No competitors configured for this brand",
        },
        "hard": [],
        "soft": [
            {
                "key": "has_brand_personas",
                "label": "Brand personas generated",
                "check": "count_gt_zero",
                "table": "personas_4d",
                "filter": {"brand_id": "{brand_id}"},
                "fix_action": "Generate personas first",
                "fix_page_link": "pages/03_👤_Personas.py",
            },
        ],
        "unlocks": [],
        "freshness": [],
    },
}
