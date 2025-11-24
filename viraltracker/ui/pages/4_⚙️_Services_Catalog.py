"""
Services Catalog - Comprehensive documentation for the service layer.

This page provides:
- Service layer architecture overview
- Method signatures and documentation
- Parameter types and return values
- Service dependencies and responsibilities
"""

import streamlit as st
import inspect
from typing import get_type_hints

# Import services
from viraltracker.services.twitter_service import TwitterService
from viraltracker.services.gemini_service import GeminiService
from viraltracker.services.stats_service import StatsService
from viraltracker.services.scraping_service import ScrapingService

# Page config
st.set_page_config(
    page_title="Services Catalog",
    page_icon="⚙️",
    layout="wide"
)

st.title("⚙️ Services Catalog")
st.markdown("**Layered architecture: Agent Layer → Service Layer**")

# ============================================================================
# Architecture Overview
# ============================================================================

st.markdown("""
The architecture is organized in two layers:

**Agent Layer (PydanticAI):**
- 1 Orchestrator Agent routes queries to specialized agents
- 5 Specialized Agents (Twitter, TikTok, YouTube, Facebook, Analysis)
- Natural language interface with Claude Sonnet 4.5
- Intelligent routing and context management

**Service Layer (Core):**
- Reusable business logic accessible from all interfaces
- Database operations, AI analysis, statistics, scraping
- Called by agents, CLI, API, and UI
""")

st.divider()

# Architecture diagram
st.subheader("Layered Architecture")

col1, col2 = st.columns([2, 3])

with col1:
    st.markdown("""
    **Agent Layer (PydanticAI)**
    - Orchestrator (routing)
    - 5 Specialized Agents

    **Service Layer (Core)**
    - `TwitterService` - Database operations
    - `GeminiService` - AI analysis
    - `StatsService` - Statistical calculations
    - `ScrapingService` - Apify integration
    """)

with col2:
    st.code("""
┌─────────────────────────────────────────────────┐
│          AGENT LAYER (PydanticAI)               │
│  ┌──────────────────────────────────────┐       │
│  │ Orchestrator (Routing)               │       │
│  └──────────────┬───────────────────────┘       │
│                 │                               │
│     ┌───────────┼───────────┬─────────┬────┐    │
│     ▼           ▼           ▼         ▼    ▼    │
│  Twitter    TikTok      YouTube    FB   Analysis│
│  (8 tools)  (5 tools)   (1 tool)  (2) (3 tools) │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────┴──────────────────────────────┐
│          SERVICE LAYER (Core)                   │
│  - TwitterService (DB access)                   │
│  - GeminiService (AI analysis)                  │
│  - StatsService (calculations)                  │
│  - ScrapingService (Apify integration)          │
└──────────────┬──────────────────────────────────┘
               │
   ┌───────────┼───────────┬──────────────┐
   │           │           │              │
   ▼           ▼           ▼              ▼
┌──────┐  ┌───────┐  ┌─────────┐  ┌────────────┐
│ CLI  │  │ Agent │  │Streamlit│  │ FastAPI    │
│      │  │(Chat) │  │  (UI)   │  │ (Webhooks) │
└──────┘  └───────┘  └─────────┘  └────────────┘
    """, language=None)

st.divider()

# ============================================================================
# Helper Functions
# ============================================================================

def get_method_signature(method):
    """Get clean method signature string"""
    try:
        sig = inspect.signature(method)
        return str(sig)
    except Exception:
        return "()"

def get_method_params(method):
    """Extract parameter information from method"""
    try:
        sig = inspect.signature(method)
        params = []

        for param_name, param in sig.parameters.items():
            if param_name in ['self', 'cls']:
                continue

            # Get type annotation
            annotation = param.annotation
            if annotation == inspect.Parameter.empty:
                param_type = "Any"
            else:
                param_type = str(annotation).replace('typing.', '').replace('<class \'', '').replace('\'>', '')

            # Get default value
            default = param.default
            if default == inspect.Parameter.empty:
                default_str = "required"
            else:
                default_str = repr(default)

            params.append({
                'name': param_name,
                'type': param_type,
                'default': default_str
            })

        return params
    except Exception:
        return []

def get_return_type(method):
    """Get return type annotation"""
    try:
        sig = inspect.signature(method)
        return_annotation = sig.return_annotation

        if return_annotation == inspect.Signature.empty:
            return "None"

        return str(return_annotation).replace('typing.', '').replace('<class \'', '').replace('\'>', '')
    except Exception:
        return "None"

def render_service(service_class, service_name, description, purpose):
    """Render a service with all its methods"""
    st.header(service_name)
    st.markdown(f"**Purpose:** {purpose}")
    st.markdown(f"**Module:** `viraltracker.services.{service_name.lower().replace('service', '_service')}`")

    st.divider()

    st.markdown(description)

    st.divider()

    st.subheader("Methods")

    # Get all public methods (exclude private methods starting with _)
    methods = []
    for name, method in inspect.getmembers(service_class):
        # Skip magic methods, private methods, and non-callables
        if name.startswith('_') or not callable(method):
            continue

        # Check if it's actually a method of this class (not inherited from object)
        if hasattr(method, '__self__') or inspect.ismethod(method) or inspect.isfunction(method):
            methods.append((name, method))

    # Sort methods alphabetically
    methods.sort(key=lambda x: x[0])

    if not methods:
        st.info("No public methods found")
        return

    # Display each method
    for method_name, method in methods:
        with st.expander(f"📌 `{method_name}()`", expanded=False):
            # Get docstring
            doc = inspect.getdoc(method)
            if doc:
                # Split docstring into summary and details
                doc_lines = doc.split('\n\n')
                summary = doc_lines[0]

                st.markdown(f"**{summary}**")

                if len(doc_lines) > 1:
                    st.divider()
                    for section in doc_lines[1:]:
                        st.markdown(section)
            else:
                st.markdown("*No documentation available*")

            st.divider()

            # Method signature
            st.markdown("**Signature:**")
            signature = get_method_signature(method)
            st.code(f"{method_name}{signature}", language="python")

            # Parameters
            params = get_method_params(method)
            if params:
                st.markdown("**Parameters:**")
                for param in params:
                    default_info = f" = `{param['default']}`" if param['default'] != "required" else " *(required)*"
                    st.markdown(f"- **`{param['name']}`** (`{param['type']}`){default_info}")

            # Return type
            return_type = get_return_type(method)
            st.markdown(f"**Returns:** `{return_type}`")

# ============================================================================
# Services Tabs
# ============================================================================

tab1, tab2, tab3, tab4 = st.tabs([
    "TwitterService",
    "GeminiService",
    "StatsService",
    "ScrapingService"
])

# TwitterService
with tab1:
    render_service(
        TwitterService,
        "TwitterService",
        """
        Database operations for Twitter data. Handles all interactions with the Supabase database,
        including fetching tweets, saving hook analyses, and managing outlier detection.

        **Key Features:**
        - Clean async interface for database queries
        - Type-safe Tweet and HookAnalysis models
        - Support for time-based and ID-based queries
        - Automatic project filtering

        **Dependencies:**
        - Supabase client (configured via environment)
        - Tweet and HookAnalysis Pydantic models
        """,
        "Database access layer for Twitter data"
    )

# GeminiService
with tab2:
    render_service(
        GeminiService,
        "GeminiService",
        """
        AI-powered hook analysis using Google Gemini. Provides intelligent classification of viral content
        with automatic rate limiting and retry logic.

        **Key Features:**
        - Automatic rate limiting (9 req/min for free tier)
        - Exponential backoff on rate limit errors
        - Structured JSON response parsing
        - Hook Intelligence framework integration

        **Classifications:**
        - **Hook Types:** 14 types (relatable_slice, shock_violation, listicle_howto, etc.)
        - **Emotional Triggers:** 10 emotions (humor, validation, curiosity, etc.)
        - **Content Patterns:** 8 patterns (question, statement, listicle, etc.)

        **Dependencies:**
        - Google Generative AI SDK
        - Gemini API key (via Config.GEMINI_API_KEY)
        """,
        "AI analysis using Google Gemini"
    )

# StatsService
with tab3:
    render_service(
        StatsService,
        "StatsService",
        """
        Statistical calculations for outlier detection and analysis. Pure computational functions
        with no side effects - all methods are static.

        **Key Features:**
        - Z-score outlier detection with trimmed statistics
        - Percentile-based outlier detection
        - Summary statistics (mean, median, std, quartiles)
        - Numpy and SciPy powered for performance

        **Methods:**
        - All methods are `@staticmethod` - no instance needed
        - Can be called directly: `StatsService.calculate_zscore_outliers(...)`

        **Dependencies:**
        - NumPy for numerical computations
        - SciPy for statistical functions
        """,
        "Statistical calculations and outlier detection"
    )

# ScrapingService
with tab4:
    render_service(
        ScrapingService,
        "ScrapingService",
        """
        Twitter scraping via Apify integration. Wraps the TwitterScraper to provide a clean
        async service layer interface for the agent and other consumers.

        **Key Features:**
        - Async interface to Twitter scraping
        - Automatic database persistence
        - Quality filtering (malformed tweet detection)
        - Returns both tweets and metadata

        **Workflow:**
        1. Scrape tweets via Apify (saves to database)
        2. Fetch saved tweets by IDs
        3. Return Tweet models + metadata

        **Dependencies:**
        - TwitterScraper (legacy scraper)
        - TwitterService (for fetching saved tweets)
        - Apify API (via scraper)
        """,
        "Twitter scraping via Apify"
    )

# ============================================================================
# Footer
# ============================================================================

st.markdown("---")
st.caption("""
**Layered Architecture Benefits:**

**Agent Layer:**
- Natural language interface with intelligent routing
- Specialized agents for each platform (Twitter, TikTok, YouTube, Facebook)
- Cross-platform analysis agent
- All powered by Claude Sonnet 4.5 (claude-sonnet-4-5-20250929)

**Service Layer:**
- Reusable across all interfaces (CLI, Agent, API, UI)
- Type-safe with Pydantic models
- Clean separation of concerns
- Easy to test and maintain

**Total Stack:** 6 agents → 4 services → 4 interfaces (CLI, Agent, API, UI)
""")
